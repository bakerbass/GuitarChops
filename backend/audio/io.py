"""Audio file I/O and peak generation for efficient waveform visualization."""
import json
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import soundfile as sf
from pydub import AudioSegment


def get_file_hash(filepath: str) -> str:
    """Generate MD5 hash of file for caching."""
    hash_md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def load_audio_info(filepath: str) -> Dict:
    """Load basic audio file information without reading entire file."""
    info = sf.info(filepath)
    return {
        "duration": info.duration,
        "samplerate": info.samplerate,
        "channels": info.channels,
        "format": info.format,
        "subtype": info.subtype,
        "frames": info.frames
    }


def convert_to_wav(filepath: str, output_dir: str = "uploads") -> str:
    """Convert audio file to WAV format if needed."""
    path = Path(filepath)
    if path.suffix.lower() == '.wav':
        return filepath
    
    # Convert using pydub
    audio = AudioSegment.from_file(filepath)
    output_path = Path(output_dir) / f"{path.stem}.wav"
    audio.export(str(output_path), format="wav")
    return str(output_path)


def generate_peaks(filepath: str, resolutions: List[int] = [10, 100, 1000], progress_callback=None) -> Dict:
    """
    Generate multi-resolution peak data for waveform visualization.
    
    Args:
        filepath: Path to audio file
        resolutions: List of downsampling factors (samples per bin)
        progress_callback: Optional callback function for progress updates
    
    Returns:
        Dictionary with peak data at multiple resolutions
    """
    # Load audio file
    if progress_callback:
        progress_callback(10, "Loading audio file...")
    audio, sr = sf.read(filepath)
    
    # Convert stereo to mono if needed
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    
    peaks = {
        "samplerate": sr,
        "duration": len(audio) / sr,
        "channels": 1,
        "resolutions": {}
    }
    
    if progress_callback:
        progress_callback(30, "Generating peak data...")
    
    for i, resolution in enumerate(resolutions):
        # Reshape audio into bins
        num_bins = len(audio) // resolution
        truncated_audio = audio[:num_bins * resolution]
        reshaped = truncated_audio.reshape(num_bins, resolution)
        
        # Calculate min, max, and RMS for each bin
        peaks["resolutions"][str(resolution)] = {
            "min": reshaped.min(axis=1).tolist(),
            "max": reshaped.max(axis=1).tolist(),
            "rms": np.sqrt(np.mean(reshaped**2, axis=1)).tolist()
        }
        
        if progress_callback:
            progress = 30 + int((i + 1) / len(resolutions) * 60)
            progress_callback(progress, f"Processing resolution {i+1}/{len(resolutions)}...")
    
    if progress_callback:
        progress_callback(95, "Finalizing...")
    
    return peaks


def save_peaks_cache(filepath: str, peaks: Dict, cache_dir: str = "cache") -> str:
    """Save peaks data to cache file."""
    file_hash = get_file_hash(filepath)
    cache_path = Path(cache_dir) / f"{file_hash}_peaks.json"
    
    with open(cache_path, 'w') as f:
        json.dump(peaks, f)
    
    return str(cache_path)


def load_peaks_cache(filepath: str, cache_dir: str = "cache") -> Dict or None:
    """Load peaks data from cache if exists."""
    file_hash = get_file_hash(filepath)
    cache_path = Path(cache_dir) / f"{file_hash}_peaks.json"
    
    if cache_path.exists():
        with open(cache_path, 'r') as f:
            return json.load(f)
    return None


def read_audio_chunk(filepath: str, start_sample: int, num_samples: int) -> Tuple[np.ndarray, int]:
    """
    Read a specific chunk of audio file without loading entire file.
    
    Args:
        filepath: Path to audio file
        start_sample: Starting sample index
        num_samples: Number of samples to read
    
    Returns:
        Tuple of (audio_data, samplerate)
    """
    with sf.SoundFile(filepath) as audio_file:
        audio_file.seek(start_sample)
        audio = audio_file.read(num_samples)
        sr = audio_file.samplerate
        
        # Convert stereo to mono if needed
        if len(audio.shape) > 1:
            audio = np.mean(audio, axis=1)
        
        return audio, sr


def get_chunks_iterator(filepath: str, chunk_duration: float = 30.0, overlap: float = 0.1):
    """
    Create an iterator that yields audio chunks with overlap.
    
    Args:
        filepath: Path to audio file
        chunk_duration: Duration of each chunk in seconds
        overlap: Overlap ratio (0.1 = 10% overlap)
    
    Yields:
        Tuple of (chunk_audio, chunk_start_time, chunk_end_time)
    """
    info = sf.info(filepath)
    sr = info.samplerate
    total_samples = info.frames
    
    chunk_samples = int(chunk_duration * sr)
    overlap_samples = int(chunk_samples * overlap)
    step_samples = chunk_samples - overlap_samples
    
    with sf.SoundFile(filepath) as audio_file:
        current_sample = 0
        
        while current_sample < total_samples:
            audio_file.seek(current_sample)
            chunk = audio_file.read(chunk_samples)
            
            # Convert stereo to mono
            if len(chunk.shape) > 1:
                chunk = np.mean(chunk, axis=1)
            
            start_time = current_sample / sr
            end_time = (current_sample + len(chunk)) / sr
            
            yield chunk, start_time, end_time
            
            current_sample += step_samples
            
            # Break if we've read past the end
            if len(chunk) < chunk_samples:
                break
