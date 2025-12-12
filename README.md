# GuitarChops

An intelligent audio segmentation tool for guitarists. Upload long audio files and automatically segment them based on silence, key signature, tempo, and note onsets with an interactive waveform interface.

## Features

- **Automatic Segmentation**: Detects silence, key changes, tempo variations, and note onsets
- **Interactive Waveform**: Visual editing with Wavesurfer.js
- **Long File Support**: Efficiently handles multi-hour recordings with chunked processing
- **Export Options**: Save individual segments with metadata tags
- **Real-time Analysis**: Progress updates via WebSocket

## Tech Stack

- **Backend**: FastAPI, librosa, aubio, essentia, pydub
- **Frontend**: Wavesurfer.js, vanilla JavaScript
- **Processing**: Chunked analysis for memory efficiency

## Setup

### Create conda environment:
```bash
conda env create -f environment.yml
conda activate guitarchops
```

### Run the server:
```bash
python -m backend.main
```

### Open in browser:
```
http://localhost:8000
```

## Usage

1. Upload an audio file (WAV, MP3, FLAC)
2. Wait for automatic analysis (silence, onset, key, tempo detection)
3. View segments on interactive waveform
4. Click to preview, drag to adjust boundaries
5. Select and export desired segments

## Architecture

```
GuitarChops/
├── backend/
│   ├── audio/          # Audio processing utilities
│   ├── api/            # FastAPI routes
│   └── main.py         # Application entry point
├── frontend/
│   ├── static/         # CSS, JS
│   └── templates/      # HTML templates
└── uploads/            # Uploaded audio files
```

## Performance

- **Peak Generation**: Multi-resolution downsampling for smooth visualization
- **Chunked Processing**: 30-60 second chunks with overlap
- **Caching**: Extracted features cached to avoid reprocessing
- **Memory Efficient**: Streams large files without loading entirely into RAM
