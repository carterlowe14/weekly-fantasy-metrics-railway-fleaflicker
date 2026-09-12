const { spawn } = require('child_process');
const express = require('express');
const path = require('path');
const os = require('os');

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 8080;

// Spawn the Python process
let pythonProcess = null;

function startPythonServer() {
  console.log('Starting Python application...');
  
  // Determine the Python command based on OS
  const pythonCmd = os.platform() === 'win32' ? 'python' : 'python3';
  
  pythonProcess = spawn(pythonCmd, ['main.py', '--serve'], {
    cwd: __dirname,
    stdio: 'inherit',
    env: process.env,
  });

  pythonProcess.on('error', (err) => {
    console.error('Failed to start Python process:', err);
  });

  pythonProcess.on('close', (code) => {
    console.log(`Python process exited with code ${code}`);
  });
}

// Health check endpoint (optional - Python app also has /health)
app.get('/health', (req, res) => {
  res.json({ status: 'ok', component: 'nodejs-wrapper' });
});

// Start listening and then start Python
const server = app.listen(PORT, '0.0.0.0', () => {
  console.log(`Node.js wrapper listening on port ${PORT}`);
  startPythonServer();
});

// Handle graceful shutdown
process.on('SIGTERM', () => {
  console.log('SIGTERM received, shutting down gracefully...');
  if (pythonProcess) {
    pythonProcess.kill('SIGTERM');
  }
  server.close(() => {
    console.log('Server closed');
    process.exit(0);
  });
});

process.on('SIGINT', () => {
  console.log('SIGINT received, shutting down gracefully...');
  if (pythonProcess) {
    pythonProcess.kill('SIGINT');
  }
  server.close(() => {
    console.log('Server closed');
    process.exit(0);
  });
});
