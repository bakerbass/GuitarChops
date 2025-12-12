"""Audio segmentation algorithms: silence, onset, key, tempo detection."""
import numpy as np
import librosa
from typing import List, Dict, Tuple
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

try:
    import aubio
    AUBIO_AVAILABLE = True
except ImportError:
    AUBIO_AVAILABLE = False

try:
    from essentia.standard import KeyExtractor
    ESSENTIA_AVAILABLE = True
except ImportError:
    ESSENTIA_AVAILABLE = False


def detect_silence_segments(filepath: str, 
                            min_silence_len: int = 500,
                            silence_thresh: int = -40,
                            seek_step: int = 10) -> List[Dict]:
    """
    Detect silence and return non-silent segments.
    
    Args:
        filepath: Path to audio file
        min_silence_len: Minimum silence length in ms
        silence_thresh: Silence threshold in dBFS
        seek_step: Step size for detection in ms
    
    Returns:
        List of segment dictionaries with start, end times and type
    """
    audio = AudioSegment.from_file(filepath)
    
    # Detect non-silent chunks
    nonsilent_ranges = detect_nonsilent(
        audio,
        min_silence_len=min_silence_len,
        silence_thresh=silence_thresh,
        seek_step=seek_step
    )
    
    segments = []
    for i, (start_ms, end_ms) in enumerate(nonsilent_ranges):
        segments.append({
            "id": f"silence_{i}",
            "start": start_ms / 1000.0,  # Convert to seconds
            "end": end_ms / 1000.0,
            "duration": (end_ms - start_ms) / 1000.0,
            "type": "silence_based",
            "confidence": 1.0
        })
    
    return segments


def detect_onsets(audio: np.ndarray, sr: int, method: str = "default") -> np.ndarray:
    """
    Detect onset times in audio.
    
    Args:
        audio: Audio signal
        sr: Sample rate
        method: Detection method ('default', 'aubio', 'librosa')
    
    Returns:
        Array of onset times in seconds
    """
    if method == "aubio" and AUBIO_AVAILABLE:
        # Use aubio for accurate onset detection
        hop_size = 512
        onset_detector = aubio.onset("complex", 2048, hop_size, sr)
        
        onsets = []
        for i in range(0, len(audio), hop_size):
            chunk = audio[i:i + hop_size]
            if len(chunk) < hop_size:
                chunk = np.pad(chunk, (0, hop_size - len(chunk)))
            
            if onset_detector(chunk.astype(np.float32)):
                onset_time = onset_detector.get_last() / sr
                onsets.append(onset_time)
        
        return np.array(onsets)
    else:
        # Use librosa as fallback
        onset_frames = librosa.onset.onset_detect(
            y=audio,
            sr=sr,
            units='frames',
            backtrack=True
        )
        onset_times = librosa.frames_to_time(onset_frames, sr=sr)
        return onset_times


def detect_onset_segments(filepath: str, 
                          chunk_duration: float = 30.0,
                          min_segment_duration: float = 0.1) -> List[Dict]:
    """
    Detect onset-based segments in audio file.
    
    Args:
        filepath: Path to audio file
        chunk_duration: Process in chunks of this duration
        min_segment_duration: Minimum segment duration in seconds
    
    Returns:
        List of segment dictionaries
    """
    from .io import get_chunks_iterator
    
    all_onsets = []
    
    # Process in chunks to handle long files
    for chunk, start_time, end_time in get_chunks_iterator(filepath, chunk_duration):
        sr = librosa.get_samplerate(filepath)
        
        # Detect onsets in this chunk
        onset_times = detect_onsets(chunk, sr)
        
        # Adjust onset times to global timeline
        global_onsets = onset_times + start_time
        all_onsets.extend(global_onsets)
    
    # Remove duplicates and sort
    all_onsets = sorted(set(all_onsets))
    
    # Create segments between onsets
    segments = []
    for i in range(len(all_onsets) - 1):
        start = all_onsets[i]
        end = all_onsets[i + 1]
        duration = end - start
        
        if duration >= min_segment_duration:
            segments.append({
                "id": f"onset_{i}",
                "start": start,
                "end": end,
                "duration": duration,
                "type": "onset_based",
                "confidence": 0.8
            })
    
    return segments


def estimate_key(audio: np.ndarray, sr: int) -> Tuple[str, str, float]:
    """
    Estimate musical key of audio segment.
    
    Args:
        audio: Audio signal
        sr: Sample rate
    
    Returns:
        Tuple of (key, scale, confidence)
    """
    if ESSENTIA_AVAILABLE:
        # Use Essentia for accurate key detection
        key_extractor = KeyExtractor()
        key, scale, strength = key_extractor(audio.astype(np.float32))
        return key, scale, float(strength)
    else:
        # Fallback to librosa chroma-based estimation
        chroma = librosa.feature.chroma_cqt(y=audio, sr=sr)
        chroma_mean = np.mean(chroma, axis=1)
        
        # Simple key estimation (Krumhansl-Schmuckler inspired)
        key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        key_idx = np.argmax(chroma_mean)
        key = key_names[key_idx]
        
        # Determine major/minor (simplified)
        major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
        minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
        
        major_corr = np.corrcoef(chroma_mean, np.roll(major_profile, key_idx))[0, 1]
        minor_corr = np.corrcoef(chroma_mean, np.roll(minor_profile, key_idx))[0, 1]
        
        scale = "major" if major_corr > minor_corr else "minor"
        confidence = max(major_corr, minor_corr)
        
        return key, scale, float(confidence)


def detect_key_segments(filepath: str, 
                       chunk_duration: float = 30.0,
                       min_segment_duration: float = 5.0) -> List[Dict]:
    """
    Detect segments with different key signatures.
    
    Args:
        filepath: Path to audio file
        chunk_duration: Duration to analyze at once
        min_segment_duration: Minimum segment duration
    
    Returns:
        List of segment dictionaries with key information
    """
    from .io import get_chunks_iterator
    
    segments = []
    current_key = None
    segment_start = 0
    
    for chunk, start_time, end_time in get_chunks_iterator(filepath, chunk_duration):
        sr = librosa.get_samplerate(filepath)
        
        # Estimate key for this chunk
        key, scale, confidence = estimate_key(chunk, sr)
        key_signature = f"{key} {scale}"
        
        # Check if key changed
        if current_key != key_signature:
            # Save previous segment if exists
            if current_key is not None and (start_time - segment_start) >= min_segment_duration:
                segments.append({
                    "id": f"key_{len(segments)}",
                    "start": segment_start,
                    "end": start_time,
                    "duration": start_time - segment_start,
                    "type": "key_based",
                    "key": current_key,
                    "confidence": confidence
                })
            
            # Start new segment
            current_key = key_signature
            segment_start = start_time
    
    # Add final segment
    if current_key is not None:
        info = librosa.get_samplerate(filepath)
        total_duration = librosa.get_duration(path=filepath)
        
        segments.append({
            "id": f"key_{len(segments)}",
            "start": segment_start,
            "end": total_duration,
            "duration": total_duration - segment_start,
            "type": "key_based",
            "key": current_key,
            "confidence": 0.7
        })
    
    return segments


def estimate_tempo(audio: np.ndarray, sr: int) -> Tuple[float, float]:
    """
    Estimate tempo (BPM) of audio segment.
    
    Args:
        audio: Audio signal
        sr: Sample rate
    
    Returns:
        Tuple of (tempo, confidence)
    """
    # Use librosa for tempo estimation
    onset_env = librosa.onset.onset_strength(y=audio, sr=sr)
    tempo = librosa.beat.tempo(onset_envelope=onset_env, sr=sr)[0]
    
    # Calculate confidence based on autocorrelation strength
    tempogram = librosa.feature.tempogram(onset_envelope=onset_env, sr=sr)
    confidence = float(np.max(tempogram) / np.mean(tempogram))
    confidence = min(confidence, 1.0)
    
    return float(tempo), confidence


def detect_tempo_segments(filepath: str,
                         chunk_duration: float = 30.0,
                         tempo_tolerance: float = 5.0,
                         min_segment_duration: float = 5.0) -> List[Dict]:
    """
    Detect segments with different tempos.
    
    Args:
        filepath: Path to audio file
        chunk_duration: Duration to analyze at once
        tempo_tolerance: BPM difference to consider as tempo change
        min_segment_duration: Minimum segment duration
    
    Returns:
        List of segment dictionaries with tempo information
    """
    from .io import get_chunks_iterator
    
    segments = []
    current_tempo = None
    segment_start = 0
    
    for chunk, start_time, end_time in get_chunks_iterator(filepath, chunk_duration):
        sr = librosa.get_samplerate(filepath)
        
        # Estimate tempo for this chunk
        tempo, confidence = estimate_tempo(chunk, sr)
        
        # Check if tempo changed significantly
        if current_tempo is None or abs(tempo - current_tempo) > tempo_tolerance:
            # Save previous segment if exists
            if current_tempo is not None and (start_time - segment_start) >= min_segment_duration:
                segments.append({
                    "id": f"tempo_{len(segments)}",
                    "start": segment_start,
                    "end": start_time,
                    "duration": start_time - segment_start,
                    "type": "tempo_based",
                    "tempo": current_tempo,
                    "confidence": confidence
                })
            
            # Start new segment
            current_tempo = tempo
            segment_start = start_time
    
    # Add final segment
    if current_tempo is not None:
        total_duration = librosa.get_duration(path=filepath)
        
        segments.append({
            "id": f"tempo_{len(segments)}",
            "start": segment_start,
            "end": total_duration,
            "duration": total_duration - segment_start,
            "type": "tempo_based",
            "tempo": current_tempo,
            "confidence": 0.7
        })
    
    return segments


def analyze_audio(filepath: str, 
                  detect_silence: bool = True,
                  detect_onset: bool = True,
                  detect_key: bool = True,
                  detect_tempo: bool = True) -> Dict:
    """
    Perform complete audio analysis with all segmentation methods.
    
    Args:
        filepath: Path to audio file
        detect_silence: Enable silence detection
        detect_onset: Enable onset detection
        detect_key: Enable key detection
        detect_tempo: Enable tempo detection
    
    Returns:
        Dictionary containing all analysis results
    """
    results = {
        "filepath": filepath,
        "segments": {
            "silence": [],
            "onset": [],
            "key": [],
            "tempo": []
        }
    }
    
    if detect_silence:
        results["segments"]["silence"] = detect_silence_segments(filepath)
    
    if detect_onset:
        results["segments"]["onset"] = detect_onset_segments(filepath)
    
    if detect_key:
        results["segments"]["key"] = detect_key_segments(filepath)
    
    if detect_tempo:
        results["segments"]["tempo"] = detect_tempo_segments(filepath)
    
    return results
