const http = require('http');
const { spawn } = require('child_process');

const PORT = 8099;
const FFMPEG = String.raw`%USERPROFILE%\AppData\Local\Microsoft\WinGet\Packages\yt-dlp.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-N-125875-g5d4d3bdc61-win64-gpl\bin\ffmpeg.exe`;

const clients = new Set();
let lastFrame = null;
let frameCount = 0;
let ffmpeg = null;
let buffer = Buffer.alloc(0);

function broadcast(frame) {
  lastFrame = frame;
  frameCount++;
  const head =
    '--frame\r\n' +
    'Content-Type: image/jpeg\r\n' +
    'Content-Length: ' + frame.length + '\r\n\r\n';
  for (const res of [...clients]) {
    try {
      res.write(head);
      res.write(frame);
      res.write('\r\n');
    } catch {
      clients.delete(res);
    }
  }
}

function parse(chunk) {
  buffer = Buffer.concat([buffer, chunk]);
  while (true) {
    const start = buffer.indexOf(Buffer.from([0xff, 0xd8]));
    if (start < 0) {
      if (buffer.length > 4 * 1024 * 1024) buffer = Buffer.alloc(0);
      return;
    }
    const end = buffer.indexOf(Buffer.from([0xff, 0xd9]), start + 2);
    if (end < 0) {
      if (start > 0) buffer = buffer.subarray(start);
      return;
    }
    const frame = buffer.subarray(start, end + 2);
    buffer = buffer.subarray(end + 2);
    broadcast(frame);
  }
}

function startCapture() {
  if (ffmpeg) return;
  const args = [
    '-hide_banner', '-loglevel', 'warning',
    '-f', 'dshow',
    '-video_size', '1280x720',
    '-framerate', '30',
    '-i', 'video=OBS-Camera',
    '-an',
    '-vf', 'scale=1280:720',
    '-q:v', '5',
    '-f', 'image2pipe',
    '-vcodec', 'mjpeg',
    'pipe:1'
  ];
  ffmpeg = spawn(FFMPEG, args, { windowsHide: true });
  ffmpeg.stdout.on('data', parse);
  ffmpeg.stderr.on('data', d => process.stderr.write(d));
  ffmpeg.on('exit', code => {
    console.error('ffmpeg exited', code);
    ffmpeg = null;
    setTimeout(startCapture, 1000);
  });
}

const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  if (req.url.startsWith('/health')) {
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ ok: true, frameCount, clients: clients.size, hasFrame: !!lastFrame }));
    return;
  }
  if (req.url.startsWith('/frame.jpg')) {
    if (!lastFrame) {
      res.statusCode = 503;
      res.end('no frame yet');
      return;
    }
    res.setHeader('Content-Type', 'image/jpeg');
    res.setHeader('Content-Length', lastFrame.length);
    res.end(lastFrame);
    return;
  }
  if (req.url.startsWith('/stream')) {
    res.writeHead(200, {
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': 'no-store, no-cache, must-revalidate',
      'Pragma': 'no-cache',
      'Connection': 'close',
      'Content-Type': 'multipart/x-mixed-replace; boundary=frame'
    });
    clients.add(res);
    req.on('close', () => clients.delete(res));
    if (lastFrame) {
      const head = '--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' + lastFrame.length + '\r\n\r\n';
      res.write(head); res.write(lastFrame); res.write('\r\n');
    }
    return;
  }
  res.statusCode = 404;
  res.end('not found');
});

server.listen(PORT, '127.0.0.1', () => {
  console.log('Dorion camera bridge listening on http://127.0.0.1:' + PORT);
  startCapture();
});

process.on('SIGINT', () => { if (ffmpeg) ffmpeg.kill(); server.close(() => process.exit(0)); });
process.on('SIGTERM', () => { if (ffmpeg) ffmpeg.kill(); server.close(() => process.exit(0)); });
