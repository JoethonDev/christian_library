import subprocess
import os
import uuid
import shutil
import platform
from pathlib import Path
from django.conf import settings
import json
import logging

logger = logging.getLogger(__name__)


class DependencyError(Exception):
    """Raised when required external dependencies are not available"""
    pass


def get_platform_command(base_command: str) -> str:
    """Get platform-specific command name"""
    system = platform.system().lower()
    
    # Platform-specific command mappings
    command_mappings = {
        'windows': {
            'gs': 'gswin64c',  # Ghostscript on Windows
        },
        'linux': {
            'gs': 'gs',
        },
        'darwin': {  # macOS
            'gs': 'gs',
        }
    }
    
    # Get system-specific mapping, fallback to original command
    system_commands = command_mappings.get(system, {})
    return system_commands.get(base_command, base_command)


def check_dependency(command: str) -> bool:
    """Check if a command/executable is available in PATH"""
    platform_command = get_platform_command(command)
    return shutil.which(platform_command) is not None


def validate_dependencies(required_commands: list) -> None:
    """Validate that all required dependencies are available"""
    missing = []
    for cmd in required_commands:
        if not check_dependency(cmd):
            missing.append(cmd)
    
    if missing:
        raise DependencyError(
            f"Missing required dependencies: {', '.join(missing)}. "
            f"Please install the required tools for media processing."
        )


class MediaProcessor:
    """Base class for media processing operations"""
    
    def __init__(self):
        self.media_root = Path(settings.MEDIA_ROOT)
        
    def ensure_directory(self, path):
        """Create directory if it doesn't exist"""
        os.makedirs(path, exist_ok=True)
        return path
    
    def get_media_info(self, file_path):
        """Get media file information using ffprobe"""
        if not check_dependency('ffprobe'):
            raise DependencyError(
                "ffprobe is required for media processing. "
                "Please install FFmpeg: https://ffmpeg.org/download.html"
            )
        
        try:
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', str(file_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            raise Exception(f"Failed to get media info: {e}")
        except FileNotFoundError:
            raise DependencyError(
                "ffprobe command not found. Please install FFmpeg and ensure it's in your PATH."
            )
    
    def get_duration(self, file_path):
        """Get duration of media file in seconds"""
        info = self.get_media_info(file_path)
        try:
            duration = float(info['format']['duration'])
            return int(duration)
        except (KeyError, ValueError):
            return 0


class VideoProcessor(MediaProcessor):
    """Handle video processing operations"""
    
    def __init__(self):
        super().__init__()
        # Validate dependencies on initialization
        self._validate_dependencies()
    
    def _validate_dependencies(self):
        """Validate that required video processing tools are available"""
        required = ['ffmpeg', 'ffprobe']
        missing = [cmd for cmd in required if not check_dependency(cmd)]
        
        if missing:
            logger.warning(
                f"Video processing dependencies not found: {', '.join(missing)}. "
                "Video processing will be disabled."
            )
            self.dependencies_available = False
        else:
            self.dependencies_available = True
    
    def compress_video(self, input_path, output_path, resolution='720'):
        """Compress video to specified resolution"""
        if not self.dependencies_available:
            raise DependencyError(
                "FFmpeg is required for video processing. "
                "Please install FFmpeg: https://ffmpeg.org/download.html"
            )
        
        try:
            self.ensure_directory(os.path.dirname(output_path))
            
            if resolution == '720':
                scale = 'scale=-2:720'
                crf = '23'
            elif resolution == '480':
                scale = 'scale=-2:480'
                crf = '25'
            else:
                raise ValueError(f"Unsupported resolution: {resolution}")
            
            cmd = [
                'ffmpeg', '-i', str(input_path),
                '-vf', scale,
                '-c:v', 'libx264', '-crf', crf,
                '-preset', 'medium',
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart',
                '-y', str(output_path)
            ]
            
            subprocess.run(cmd, check=True)
            return output_path
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"Video compression failed: {e}")
    
    def generate_hls(self, input_path, output_dir, resolution='720', hybrid=True):
        """Generate HLS playlist and segments. If hybrid=True, skip video encoding (copy video), encode audio only."""
        try:
            output_dir = Path(output_dir)
            self.ensure_directory(output_dir)
            playlist_path = output_dir / 'playlist.m3u8'
            segment_pattern = output_dir / 'segment_%03d.ts'

            logger = logging.getLogger(__name__)

            if hybrid:
                # Hybrid mode: copy video, encode audio only
                cmd = [
                    'ffmpeg', '-i', str(input_path),
                    '-c:v', 'copy',
                    '-c:a', 'aac', '-b:a', '128k', '-ac', '2', '-ar', '44100',
                    '-hls_time', '6',
                    '-hls_list_size', '0',
                    '-hls_segment_filename', str(segment_pattern),
                    '-hls_playlist_type', 'vod',
                    '-threads', '2',
                    '-loglevel', 'info',
                    '-y', str(playlist_path)
                ]
                logger.info("Hybrid HLS: Skipping video encoding, encoding audio only.")
            else:
                # Standard: encode video and audio
                # Optimization parameters
                if resolution == '720':
                    scale = "scale='min(1280,iw)':-2"
                    bitrate = '2000k'
                    maxrate = '2200k'
                    bufsize = '4000k'
                elif resolution == '480':
                    scale = "scale='min(854,iw)':-2"
                    bitrate = '1000k'
                    maxrate = '1100k'
                    bufsize = '2000k'
                else:
                    raise ValueError(f"Unsupported resolution: {resolution}")

                cmd = [
                    'ffmpeg', '-i', str(input_path),
                    '-vf', scale,
                    '-c:v', 'libx264', '-preset', 'veryfast',
                    '-b:v', bitrate, '-maxrate', maxrate, '-bufsize', bufsize,
                    '-g', '48', '-sc_threshold', '0',
                    '-c:a', 'aac', '-b:a', '128k', '-ac', '2', '-ar', '44100',
                    '-hls_time', '6',
                    '-hls_list_size', '0',
                    '-hls_segment_filename', str(segment_pattern),
                    '-hls_playlist_type', 'vod',
                    '-threads', '2',
                    '-loglevel', 'info',
                    '-y', str(playlist_path)
                ]

            # Log the command for observability
            logger.info(f"Running FFmpeg command: {' '.join(str(x) for x in cmd)}")

            # Capture stdout/stderr for Celery logs
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"FFmpeg stdout: {result.stdout}")
            logger.info(f"FFmpeg stderr: {result.stderr}")
            return playlist_path

        except subprocess.CalledProcessError as e:
            logger = logging.getLogger(__name__)
            logger.error(f"HLS generation failed: {e}\nstdout: {e.stdout}\nstderr: {e.stderr}")
            raise Exception(f"HLS generation failed: {e}")


class AudioProcessor(MediaProcessor):
    """Handle audio processing operations"""
    
    def __init__(self):
        super().__init__()
        self._validate_dependencies()
    
    def _validate_dependencies(self):
        """Validate that required audio processing tools are available"""
        required = ['ffmpeg', 'ffprobe']
        missing = [cmd for cmd in required if not check_dependency(cmd)]
        
        if missing:
            logger.warning(
                f"Audio processing dependencies not found: {', '.join(missing)}. "
                "Audio processing will be disabled."
            )
            self.dependencies_available = False
        else:
            self.dependencies_available = True
    
    def compress_audio(self, input_path, output_path, target_bitrate='192k', max_size_mb=50):
        """Compress audio to target bitrate with size limit"""
        if not self.dependencies_available:
            raise DependencyError(
                "FFmpeg is required for audio processing. "
                "Please install FFmpeg: https://ffmpeg.org/download.html"
            )
        
        try:
            self.ensure_directory(os.path.dirname(output_path))
            
            cmd = [
                'ffmpeg', '-i', str(input_path),
                '-c:a', 'libmp3lame',
                '-b:a', target_bitrate,
                '-ar', '44100',
                '-ac', '2',
                '-y', str(output_path)
            ]
            
            subprocess.run(cmd, check=True)
            
            # Check file size
            file_size = os.path.getsize(output_path)
            max_size_bytes = max_size_mb * 1024 * 1024
            
            if file_size > max_size_bytes:
                # Try lower bitrate if file is too large
                lower_bitrate = '128k' if target_bitrate == '192k' else '96k'
                cmd[6] = lower_bitrate  # Replace bitrate parameter
                
                subprocess.run(cmd, check=True)
                file_size = os.path.getsize(output_path)
                
                if file_size > max_size_bytes:
                    raise Exception(f"Compressed file ({file_size/1024/1024:.1f}MB) exceeds {max_size_mb}MB limit")
            
            return output_path, file_size
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"Audio compression failed: {e}")
    
    def extract_metadata(self, file_path):
        """Extract audio metadata"""
        if not self.dependencies_available:
            # Return default metadata if dependencies not available
            logger.warning("Audio metadata extraction skipped - FFmpeg not available")
            return {
                'duration': 0,
                'bitrate': 192000,
                'sample_rate': 44100,
                'channels': 2,
            }
        
        try:
            info = self.get_media_info(file_path)
            
            audio_stream = None
            for stream in info.get('streams', []):
                if stream.get('codec_type') == 'audio':
                    audio_stream = stream
                    break
            
            if not audio_stream:
                logger.warning("No audio stream found, using defaults")
                return {
                    'duration': 0,
                    'bitrate': 192000,
                    'sample_rate': 44100,
                    'channels': 2,
                }
            
            return {
                'duration': self.get_duration(file_path),
                'bitrate': int(audio_stream.get('bit_rate', 192000)),
                'sample_rate': int(audio_stream.get('sample_rate', 44100)),
                'channels': int(audio_stream.get('channels', 2)),
            }
        except Exception as e:
            logger.warning(f"Failed to extract audio metadata: {e}")
            return {
                'duration': 0,
                'bitrate': 192000,
                'sample_rate': 44100,
                'channels': 2,
            }


class PDFProcessor:
    """Handle PDF processing operations"""
    
    def __init__(self):
        self.media_root = Path(settings.MEDIA_ROOT)
        self._validate_dependencies()
    
    def _validate_dependencies(self):
        """Validate that required PDF processing tools are available"""
        required = ['gs']  # Ghostscript
        optional = ['pdfinfo']  # Poppler utils
        
        missing = [cmd for cmd in required if not check_dependency(cmd)]
        missing_optional = [cmd for cmd in optional if not check_dependency(cmd)]
        
        if missing:
            logger.warning(
                f"PDF processing dependencies not found: {', '.join(missing)}. "
                "PDF optimization will be disabled."
            )
            self.optimization_available = False
        else:
            self.optimization_available = True
            
        if missing_optional:
            logger.warning(
                f"Optional PDF tools not found: {', '.join(missing_optional)}. "
                "PDF metadata extraction may be limited."
            )
            self.metadata_available = len(missing_optional) == 0
        else:
            self.metadata_available = True
    
    def optimize_pdf(self, input_path, output_path):
        """Optimize PDF using Ghostscript"""
        if not self.optimization_available:
            raise DependencyError(
                "Ghostscript is required for PDF optimization. "
                "Please install Ghostscript: https://www.ghostscript.com/download/gsdnld.html"
            )
        
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            # Use platform-specific Ghostscript command
            gs_command = get_platform_command('gs')
            cmd = [
                gs_command, '-sDEVICE=pdfwrite', '-dCompatibilityLevel=1.4',
                '-dPDFSETTINGS=/ebook', '-dNOPAUSE', '-dQUIET',
                '-dBATCH', f'-sOutputFile={output_path}', str(input_path)
            ]
            
            subprocess.run(cmd, check=True)
            return output_path
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"PDF optimization failed: {e}")
        except FileNotFoundError:
            gs_command = get_platform_command('gs')
            raise DependencyError(
                f"Ghostscript command '{gs_command}' not found. "
                "Please install Ghostscript and ensure it's in your PATH."
            )
    
    def get_pdf_info(self, file_path):
        """Get PDF information"""
        file_size = os.path.getsize(file_path)
        
        # Try to get page count using pdfinfo if available
        page_count = 1  # Default
        
        if self.metadata_available and check_dependency('pdfinfo'):
            try:
                cmd = ['pdfinfo', str(file_path)]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                
                for line in result.stdout.split('\n'):
                    if line.startswith('Pages:'):
                        page_count = int(line.split(':')[1].strip())
                        break
            except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
                logger.warning(f"Failed to get PDF page count using pdfinfo: {e}")
                # Fallback: try to estimate from file size (very rough)
                page_count = max(1, file_size // (50 * 1024))  # Assume ~50KB per page
        else:
            logger.info("pdfinfo not available, using estimated page count based on file size")
            # Rough estimation: assume average page is 50KB
            page_count = max(1, file_size // (50 * 1024))
        
        return {
            'file_size': file_size,
            'page_count': page_count
        }


def generate_unique_filename(original_filename, content_type):
    """Generate UUID-based filename while preserving extension"""
    file_uuid = uuid.uuid4()
    extension = Path(original_filename).suffix.lower()
    
    # Validate extension based on content type
    valid_extensions = {
        'video': ['.mp4', '.avi', '.mov', '.mkv', '.webm'],
        'audio': ['.mp3', '.wav', '.aac', '.flac', '.ogg'],
        'pdf': ['.pdf']
    }
    
    if extension not in valid_extensions.get(content_type, []):
        raise ValueError(f"Invalid file extension {extension} for content type {content_type}")
    
    return f"{file_uuid}{extension}"


def get_storage_path(content_type, file_type='original'):
    """Get the storage path for different content types and file types"""
    paths = {
        'video': {
            'original': 'original/videos',
            'hls_720p': 'hls/videos/{uuid}/720p',
            'hls_480p': 'hls/videos/{uuid}/480p'
        },
        'audio': {
            'original': 'original/audio',
            'compressed': 'compressed/audio'
        },
        'pdf': {
            'original': 'original/pdf',
            'optimized': 'optimized/pdf'
        }
    }
    
    return paths.get(content_type, {}).get(file_type, 'original')