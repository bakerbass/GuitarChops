"""FastAPI application entry point."""
import os
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, JSONResponse
from fastapi.requests import Request
import uvicorn
import json
import asyncio
from typing import Dict, List

from backend.audio.io import (
    generate_peaks, save_peaks_cache, load_peaks_cache,
    load_audio_info, convert_to_wav, get_file_hash
)
from backend.audio.segmentation import analyze_audio

# Create FastAPI app
app = FastAPI(title="GuitarChops", version="1.0.0")

# Setup directories
UPLOAD_DIR = Path("uploads")
CACHE_DIR = Path("cache")
STATIC_DIR = Path("frontend/static")
TEMPLATE_DIR = Path("frontend/templates")

UPLOAD_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Setup templates
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# Store active analysis tasks
analysis_tasks: Dict[str, Dict] = {}
# Store active upload tasks
upload_tasks: Dict[str, Dict] = {}


@app.get("/")
async def home(request: Request):
    """Serve main application page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/load-default-file")
async def load_default_file():
    """
    Load the default audio file from the repo.
    
    Returns file info and peaks data.
    """
    # Look for audio file in the repo root
    audio_files = list(Path(".").glob("*.wav")) + list(Path(".").glob("*.mp3"))
    
    if not audio_files:
        raise HTTPException(status_code=404, detail="No audio file found in repo")
    
    # Use the first audio file found
    file_path = str(audio_files[0])
    
    # Convert to WAV if needed
    wav_path = await asyncio.to_thread(convert_to_wav, file_path, str(UPLOAD_DIR))
    
    # Generate file ID
    file_id = await asyncio.to_thread(get_file_hash, wav_path)
    
    # Load audio info
    info = await asyncio.to_thread(load_audio_info, wav_path)
    
    # Check if peaks are cached
    peaks = await asyncio.to_thread(load_peaks_cache, wav_path, str(CACHE_DIR))
    
    if peaks is None:
        # Generate peaks
        peaks = await asyncio.to_thread(generate_peaks, wav_path)
        await asyncio.to_thread(save_peaks_cache, wav_path, peaks, str(CACHE_DIR))
    
    return JSONResponse({
        "file_id": file_id,
        "filename": Path(file_path).name,
        "wav_path": str(wav_path),
        "info": info,
        "peaks": peaks,
        "audio_url": f"/api/audio/{file_id}"
    })


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Upload audio file and generate peaks data.
    
    Returns task ID for progress tracking.
    """
    # Generate upload task ID
    task_id = f"upload_{file.filename}_{int(asyncio.get_event_loop().time() * 1000)}"
    
    # Initialize task
    upload_tasks[task_id] = {
        "status": "uploading",
        "progress": 0,
        "message": "Uploading file...",
        "filename": file.filename
    }
    
    # Start upload processing in background
    asyncio.create_task(process_upload(task_id, file))
    
    return JSONResponse({"task_id": task_id})


async def process_upload(task_id: str, file: UploadFile):
    """Process file upload and peak generation with progress updates."""
    try:
        # Save uploaded file
        upload_tasks[task_id]["progress"] = 5
        upload_tasks[task_id]["message"] = "Saving file..."
        
        file_path = UPLOAD_DIR / file.filename
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # Convert to WAV if needed
        upload_tasks[task_id]["progress"] = 10
        upload_tasks[task_id]["message"] = "Converting to WAV..."
        wav_path = await asyncio.to_thread(convert_to_wav, str(file_path), str(UPLOAD_DIR))
        
        # Generate file ID
        file_id = await asyncio.to_thread(get_file_hash, wav_path)
        
        # Load audio info
        upload_tasks[task_id]["progress"] = 15
        upload_tasks[task_id]["message"] = "Reading audio info..."
        info = await asyncio.to_thread(load_audio_info, wav_path)
        
        # Check if peaks are cached
        peaks = await asyncio.to_thread(load_peaks_cache, wav_path, str(CACHE_DIR))
        
        if peaks is None:
            # Generate peaks with progress callback
            def progress_callback(progress: int, message: str):
                upload_tasks[task_id]["progress"] = progress
                upload_tasks[task_id]["message"] = message
            
            peaks = await asyncio.to_thread(generate_peaks, wav_path, [10, 100, 1000], progress_callback)
            await asyncio.to_thread(save_peaks_cache, wav_path, peaks, str(CACHE_DIR))
        else:
            upload_tasks[task_id]["progress"] = 90
            upload_tasks[task_id]["message"] = "Loading cached peaks..."
        
        # Complete
        upload_tasks[task_id]["status"] = "completed"
        upload_tasks[task_id]["progress"] = 100
        upload_tasks[task_id]["message"] = "Complete!"
        upload_tasks[task_id]["result"] = {
            "file_id": file_id,
            "filename": file.filename,
            "wav_path": str(wav_path),
            "info": info,
            "peaks": peaks
        }
        
    except Exception as e:
        upload_tasks[task_id]["status"] = "error"
        upload_tasks[task_id]["error"] = str(e)
        upload_tasks[task_id]["message"] = f"Error: {str(e)}"


@app.get("/api/file/{file_id}/info")
async def get_file_info(file_id: str):
    """Get audio file information."""
    # Find file by hash
    for file_path in UPLOAD_DIR.glob("*.wav"):
        if get_file_hash(str(file_path)) == file_id:
            info = load_audio_info(str(file_path))
            return JSONResponse(info)
    
    raise HTTPException(status_code=404, detail="File not found")


@app.get("/api/file/{file_id}/peaks")
async def get_peaks(file_id: str):
    """Get cached peaks data for visualization."""
    # Find file by hash
    for file_path in UPLOAD_DIR.glob("*.wav"):
        if get_file_hash(str(file_path)) == file_id:
            peaks = load_peaks_cache(str(file_path), str(CACHE_DIR))
            if peaks:
                return JSONResponse(peaks)
            else:
                # Generate if not cached
                peaks = generate_peaks(str(file_path))
                save_peaks_cache(str(file_path), peaks, str(CACHE_DIR))
                return JSONResponse(peaks)
    
    raise HTTPException(status_code=404, detail="File not found")


@app.post("/api/file/{file_id}/analyze")
async def start_analysis(file_id: str, 
                         silence: bool = True,
                         onset: bool = True,
                         key: bool = True,
                         tempo: bool = True):
    """
    Start audio analysis in background.
    
    Returns task ID for WebSocket progress tracking.
    """
    # Find file by hash
    file_path = None
    for path in UPLOAD_DIR.glob("*.wav"):
        if get_file_hash(str(path)) == file_id:
            file_path = str(path)
            break
    
    if not file_path:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Create task
    task_id = f"analysis_{file_id}"
    analysis_tasks[task_id] = {
        "status": "started",
        "progress": 0,
        "file_path": file_path,
        "results": None
    }
    
    # Start analysis in background
    asyncio.create_task(run_analysis(task_id, file_path, silence, onset, key, tempo))
    
    return JSONResponse({"task_id": task_id})


async def run_analysis(task_id: str, file_path: str, 
                      detect_silence: bool, detect_onset: bool,
                      detect_key: bool, detect_tempo: bool):
    """Run analysis and update progress."""
    try:
        analysis_tasks[task_id]["status"] = "running"
        analysis_tasks[task_id]["progress"] = 10
        
        # Run analysis (this is CPU-bound, consider using process pool for production)
        results = await asyncio.to_thread(
            analyze_audio,
            file_path,
            detect_silence=detect_silence,
            detect_onset=detect_onset,
            detect_key=detect_key,
            detect_tempo=detect_tempo
        )
        
        analysis_tasks[task_id]["progress"] = 100
        analysis_tasks[task_id]["status"] = "completed"
        analysis_tasks[task_id]["results"] = results
        
    except Exception as e:
        analysis_tasks[task_id]["status"] = "error"
        analysis_tasks[task_id]["error"] = str(e)


@app.get("/api/task/{task_id}/status")
async def get_task_status(task_id: str):
    """Get analysis task status."""
    if task_id not in analysis_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return JSONResponse(analysis_tasks[task_id])


@app.websocket("/ws/progress/{task_id}")
async def progress_websocket(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for real-time progress updates."""
    await websocket.accept()
    
    try:
        while True:
            # Check both upload and analysis tasks
            task = None
            if task_id in upload_tasks:
                task = upload_tasks[task_id]
            elif task_id in analysis_tasks:
                task = analysis_tasks[task_id]
            
            if task:
                response = {
                    "status": task["status"],
                    "progress": task["progress"]
                }
                if "message" in task:
                    response["message"] = task["message"]
                if task["status"] == "completed" and "result" in task:
                    response["result"] = task["result"]
                if task["status"] == "error" and "error" in task:
                    response["error"] = task["error"]
                
                await websocket.send_json(response)
                
                if task["status"] in ["completed", "error"]:
                    break
            
            await asyncio.sleep(0.3)
    
    except WebSocketDisconnect:
        pass


@app.get("/api/file/{file_id}/segments")
async def get_segments(file_id: str):
    """Get analysis results (segments) for a file."""
    task_id = f"analysis_{file_id}"
    
    if task_id not in analysis_tasks:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    task = analysis_tasks[task_id]
    
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="Analysis not completed")
    
    return JSONResponse(task["results"])


@app.post("/api/export")
async def export_segments(file_id: str, segment_ids: List[str]):
    """
    Export selected segments as individual audio files.
    
    Returns download URLs for exported files.
    """
    from pydub import AudioSegment
    
    # Find file
    file_path = None
    for path in UPLOAD_DIR.glob("*.wav"):
        if get_file_hash(str(path)) == file_id:
            file_path = str(path)
            break
    
    if not file_path:
        raise HTTPException(status_code=404, detail="File not found")
    
    # Get segments
    task_id = f"analysis_{file_id}"
    if task_id not in analysis_tasks or analysis_tasks[task_id]["status"] != "completed":
        raise HTTPException(status_code=400, detail="Analy


@app.get("/api/audio/{file_id}")
async def stream_audio(file_id: str):
    """Stream audio file for playback."""
    # Find file by hash
    for file_path in UPLOAD_DIR.glob("*.wav"):
        if get_file_hash(str(file_path)) == file_id:
            return FileResponse(str(file_path), media_type="audio/wav")
    
    raise HTTPException(status_code=404, detail="Audio file not found")sis not completed")
    
    results = analysis_tasks[task_id]["results"]
    all_segments = []
    for seg_type in results["segments"].values():
        all_segments.extend(seg_type)
    
    # Load audio
    audio = AudioSegment.from_file(file_path)
    
    # Export selected segments
    exported_files = []
    export_dir = UPLOAD_DIR / "exports"
    export_dir.mkdir(exist_ok=True)
    
    for seg_id in segment_ids:
        segment = next((s for s in all_segments if s["id"] == seg_id), None)
        if segment:
            start_ms = int(segment["start"] * 1000)
            end_ms = int(segment["end"] * 1000)
            
            segment_audio = audio[start_ms:end_ms]
            output_filename = f"{seg_id}.wav"
            output_path = export_dir / output_filename
            
            segment_audio.export(str(output_path), format="wav")
            exported_files.append({
                "segment_id": seg_id,
                "filename": output_filename,
                "url": f"/api/download/{output_filename}"
            })
    
    return JSONResponse({"exported": exported_files})


@app.get("/api/download/{filename}")
async def download_file(filename: str):
    """Download exported segment file."""
    file_path = UPLOAD_DIR / "exports" / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(str(file_path), filename=filename)


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
