// GuitarChops Application
let wavesurfer = null;
let currentFileId = null;
let currentFilename = null;
let allSegments = [];
let selectedSegments = new Set();
let currentFilter = 'all';

// Initialize application
document.addEventListener('DOMContentLoaded', () => {
    initializeWavesurfer();
    initializeControls();
    loadDefaultFile();
});

// Load default file on startup
async function loadDefaultFile() {
    try {
        const response = await fetch('/api/load-default-file');
        const data = await response.json();
        
        // Store file info
        currentFileId = data.file_id;
        currentFilename = data.filename;
        
        // Display file info
        displayFileInfo(data);
        
        // Load waveform from server audio
        wavesurfer.load(data.audio_url);
        
    } catch (error) {
        console.error('Failed to load default file:', error);
        alert('Failed to load audio file. Please check that an audio file exists in the repo.');
    }
}

// Display file information
function displayFileInfo(data) {
    document.getElementById('infoFilename').textContent = data.filename;
    document.getElementById('infoDuration').textContent = formatTime(data.info.duration);
    document.getElementById('infoSamplerate').textContent = `${data.info.samplerate} Hz`;
    document.getElementById('infoChannels').textContent = data.info.channels;
}

// Initialize Wavesurfer
function initializeWavesurfer() {
    wavesurfer = WaveSurfer.create({
        container: '#waveform',
        waveColor: '#3b82f6',
        progressColor: '#8b5cf6',
        cursorColor: '#ef4444',
        barWidth: 2,
        barGap: 1,
        height: 128,
        normalize: true,
        backend: 'WebAudio'
    });

    wavesurfer.on('ready', () => {
        const duration = wavesurfer.getDuration();
        document.getElementById('totalTime').textContent = formatTime(duration);
    });

    wavesurfer.on('audioprocess', () => {
        const currentTime = wavesurfer.getCurrentTime();
        document.getElementById('currentTime').textContent = formatTime(currentTime);
    });
}

// Initialize controls
function initializeControls() {
    // Playback controls
    document.getElementById('playPauseBtn').addEventListener('click', () => {
        wavesurfer.playPause();
        const btn = document.getElementById('playPauseBtn');
        btn.textContent = wavesurfer.isPlaying() ? '⏸ Pause' : '▶ Play';
    });

    document.getElementById('stopBtn').addEventListener('click', () => {
        wavesurfer.stop();
        document.getElementById('playPauseBtn').textContent = '▶ Play';
    });

    // Zoom control
    document.getElementById('zoomSlider').addEventListener('input', (e) => {
        wavesurfer.zoom(Number(e.target.value));
    });

    // Analysis button
    document.getElementById('analyzeBtn').addEventListener('click', startAnalysis);

    // Export controls
    document.getElementById('selectAllBtn').addEventListener('click', toggleSelectAll);
    document.getElementById('exportBtn').addEventListener('click', exportSelected);

    // Filter buttons
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            currentFilter = e.target.dataset.filter;
            renderSegments();
        });
    });
}

// Start analysis
async function startAnalysis() {
    const silence = document.getElementById('detectSilence').checked;
    const onset = document.getElementById('detectOnset').checked;
    const key = document.getElementById('detectKey').checked;
    const tempo = document.getElementById('detectTempo').checked;

    if (!currentFileId) {
        alert('Please wait for the file to load.');
        return;
    }

    try {
        // Disable button
        const analyzeBtn = document.getElementById('analyzeBtn');
        analyzeBtn.disabled = true;
        analyzeBtn.textContent = '🔄 Analyzing...';

        // Show progress bar
        const progressBar = document.getElementById('progressBar');
        progressBar.classList.remove('hidden');

        // Start analysis
        const response = await fetch(`/api/file/${currentFileId}/analyze?silence=${silence}&onset=${onset}&key=${key}&tempo=${tempo}`, {
            method: 'POST'
        });

        const data = await response.json();
        const taskId = data.task_id;

        // Connect to WebSocket for progress
        connectProgressWebSocket(taskId);

    } catch (error) {
        console.error('Analysis error:', error);
        alert('Failed to start analysis. Please try again.');
        resetAnalysisButton();
    }
}

// Connect to progress WebSocket
function connectProgressWebSocket(taskId) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/progress/${taskId}`);

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        updateProgress(data.progress);

        if (data.status === 'completed') {
            ws.close();
            loadAnalysisResults();
        } else if (data.status === 'error') {
            ws.close();
            alert('Analysis failed. Please try again.');
            resetAnalysisButton();
        }
    };

    ws.onerror = () => {
        alert('Connection error. Please refresh and try again.');
        resetAnalysisButton();
    };
}

// Update progress bar
function updateProgress(progress) {
    document.getElementById('progressFill').style.width = `${progress}%`;
    document.getElementById('progressText').textContent = `Analyzing... ${progress}%`;
}

// Load analysis results
async function loadAnalysisResults() {
    try {
        const response = await fetch(`/api/file/${currentFileId}/segments`);
        const data = await response.json();

        // Flatten all segments
        allSegments = [];
        for (const [type, segments] of Object.entries(data.segments)) {
            allSegments.push(...segments);
        }

        // Display segments
        displaySegments(allSegments);

        // Reset analysis button
        resetAnalysisButton();

        // Hide progress bar
        document.getElementById('progressBar').classList.add('hidden');

        // Show segments section
        document.getElementById('segmentsSection').classList.remove('hidden');

    } catch (error) {
        console.error('Failed to load results:', error);
        alert('Failed to load analysis results.');
        resetAnalysisButton();
    }
}

// Reset analysis button
function resetAnalysisButton() {
    const analyzeBtn = document.getElementById('analyzeBtn');
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = '🔍 Analyze Audio';
}

// Display segments on waveform
function displaySegments(segments) {
    // Clear existing regions
    wavesurfer.clearRegions();

    // Color map for segment types
    const colorMap = {
        'silence_based': 'rgba(59, 130, 246, 0.3)',
        'onset_based': 'rgba(139, 92, 246, 0.3)',
        'key_based': 'rgba(16, 185, 129, 0.3)',
        'tempo_based': 'rgba(245, 158, 11, 0.3)'
    };

    // Add regions to waveform
    segments.forEach(segment => {
        wavesurfer.addRegion({
            start: segment.start,
            end: segment.end,
            color: colorMap[segment.type] || 'rgba(100, 100, 100, 0.3)',
            drag: false,
            resize: false,
            id: segment.id
        });
    });

    renderSegments();
}

// Render segments list
function renderSegments() {
    const segmentsList = document.getElementById('segmentsList');
    segmentsList.innerHTML = '';

    // Filter segments
    const filteredSegments = currentFilter === 'all' 
        ? allSegments 
        : allSegments.filter(s => s.type === currentFilter);

    if (filteredSegments.length === 0) {
        segmentsList.innerHTML = '<p style="color: var(--text-secondary); text-align: center; padding: 2rem;">No segments found</p>';
        return;
    }

    // Render each segment
    filteredSegments.forEach(segment => {
        const item = createSegmentItem(segment);
        segmentsList.appendChild(item);
    });
}

// Create segment list item
function createSegmentItem(segment) {
    const div = document.createElement('div');
    div.className = 'segment-item';
    if (selectedSegments.has(segment.id)) {
        div.classList.add('selected');
    }

    // Build metadata string
    let metadata = '';
    if (segment.key) metadata += `Key: ${segment.key} | `;
    if (segment.tempo) metadata += `Tempo: ${segment.tempo.toFixed(1)} BPM | `;
    metadata += `Confidence: ${(segment.confidence * 100).toFixed(0)}%`;

    div.innerHTML = `
        <input type="checkbox" class="segment-checkbox" data-id="${segment.id}" 
               ${selectedSegments.has(segment.id) ? 'checked' : ''}>
        <div class="segment-info">
            <div class="segment-header">
                <span class="segment-id">${segment.id}</span>
                <span class="segment-type">${segment.type.replace('_', ' ')}</span>
            </div>
            <div class="segment-details">
                ${formatTime(segment.start)} - ${formatTime(segment.end)} (${formatTime(segment.duration)})
                <br>
                ${metadata}
            </div>
        </div>
    `;

    // Click to select
    div.addEventListener('click', (e) => {
        if (e.target.type !== 'checkbox') {
            toggleSegmentSelection(segment.id);
            wavesurfer.setTime(segment.start);
        }
    });

    // Checkbox change
    div.querySelector('.segment-checkbox').addEventListener('change', (e) => {
        e.stopPropagation();
        toggleSegmentSelection(segment.id);
    });

    return div;
}

// Toggle segment selection
function toggleSegmentSelection(segmentId) {
    if (selectedSegments.has(segmentId)) {
        selectedSegments.delete(segmentId);
    } else {
        selectedSegments.add(segmentId);
    }
    
    updateSelectedCount();
    renderSegments();
}

// Toggle select all
function toggleSelectAll() {
    const filteredSegments = currentFilter === 'all' 
        ? allSegments 
        : allSegments.filter(s => s.type === currentFilter);

    if (selectedSegments.size === filteredSegments.length) {
        // Deselect all filtered
        filteredSegments.forEach(s => selectedSegments.delete(s.id));
    } else {
        // Select all filtered
        filteredSegments.forEach(s => selectedSegments.add(s.id));
    }

    updateSelectedCount();
    renderSegments();
}

// Update selected count
function updateSelectedCount() {
    const count = selectedSegments.size;
    document.getElementById('selectedCount').textContent = `${count} segment${count !== 1 ? 's' : ''} selected`;
    document.getElementById('exportBtn').disabled = count === 0;
}

// Export selected segments
async function exportSelected() {
    if (selectedSegments.size === 0) return;

    try {
        const exportBtn = document.getElementById('exportBtn');
        exportBtn.disabled = true;
        exportBtn.textContent = '⏳ Exporting...';

        const response = await fetch('/api/export', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                file_id: currentFileId,
                segment_ids: Array.from(selectedSegments)
            })
        });

        const data = await response.json();

        // Download each exported file
        for (const file of data.exported) {
            const link = document.createElement('a');
            link.href = file.url;
            link.download = file.filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            
            // Small delay between downloads
            await new Promise(resolve => setTimeout(resolve, 100));
        }

        alert(`Successfully exported ${data.exported.length} segments!`);

        exportBtn.disabled = false;
        exportBtn.textContent = '💾 Export Selected';

    } catch (error) {
        console.error('Export error:', error);
        alert('Failed to export segments. Please try again.');
        
        const exportBtn = document.getElementById('exportBtn');
        exportBtn.disabled = false;
        exportBtn.textContent = '💾 Export Selected';
    }
}

// Utility: Format time
function formatTime(seconds) {
    if (isNaN(seconds) || seconds === null) return '0:00';
    
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}
