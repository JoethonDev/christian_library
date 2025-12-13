"""
Management command to check media processing dependencies
"""
import shutil
import subprocess
import platform
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from core.utils.media_processing import check_dependency, get_platform_command


class Command(BaseCommand):
    help = 'Check media processing dependencies and provide installation instructions'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--install',
            action='store_true',
            help='Show installation instructions for missing dependencies',
        )
        parser.add_argument(
            '--platform',
            type=str,
            choices=['windows', 'macos', 'ubuntu', 'debian', 'fedora', 'arch'],
            default='windows',
            help='Platform for installation instructions',
        )
    
    def handle(self, *args, **options):
        current_platform = platform.system().lower()
        self.stdout.write(self.style.HTTP_INFO(f'Checking media processing dependencies on {current_platform.title()}...'))
        
        dependencies = {
            'ffmpeg': {
                'description': 'Video and audio processing',
                'required_for': ['video HLS conversion', 'audio compression', 'metadata extraction'],
                'windows': 'Download from https://ffmpeg.org/download.html or use chocolatey: choco install ffmpeg',
                'macos': 'brew install ffmpeg',
                'ubuntu': 'sudo apt update && sudo apt install ffmpeg',
                'debian': 'sudo apt update && sudo apt install ffmpeg',
                'fedora': 'sudo dnf install ffmpeg',
                'arch': 'sudo pacman -S ffmpeg'
            },
            'ffprobe': {
                'description': 'Media file analysis (usually included with FFmpeg)',
                'required_for': ['media metadata extraction', 'duration calculation'],
                'note': 'Usually installed automatically with FFmpeg'
            },
            'gs': {
                'description': 'Ghostscript for PDF processing',
                'required_for': ['PDF optimization', 'PDF compression'],
                'windows': 'Download from https://www.ghostscript.com/download/gsdnld.html or use chocolatey: choco install ghostscript',
                'macos': 'brew install ghostscript',
                'ubuntu': 'sudo apt update && sudo apt install ghostscript',
                'debian': 'sudo apt update && sudo apt install ghostscript',
                'fedora': 'sudo dnf install ghostscript',
                'arch': 'sudo pacman -S ghostscript',
                'note_windows': 'On Windows, this checks for "gswin64c" command'
            },
            'pdfinfo': {
                'description': 'PDF metadata extraction (part of Poppler utils)',
                'required_for': ['PDF page count', 'PDF metadata'],
                'windows': 'Download Poppler for Windows from http://blog.alivate.com.au/poppler-windows/',
                'macos': 'brew install poppler',
                'ubuntu': 'sudo apt update && sudo apt install poppler-utils',
                'debian': 'sudo apt update && sudo apt install poppler-utils',
                'fedora': 'sudo dnf install poppler-utils',
                'arch': 'sudo pacman -S poppler'
            }
        }
        
        missing = []
        available = []
        
        for cmd, info in dependencies.items():
            actual_command = get_platform_command(cmd)
            if check_dependency(cmd):
                available.append((cmd, info))
                command_info = f' (using "{actual_command}")' if actual_command != cmd else ''
                self.stdout.write(
                    self.style.SUCCESS(f'✓ {cmd}: {info["description"]}{command_info}')
                )
            else:
                missing.append((cmd, info))
                command_info = f' (looking for "{actual_command}")' if actual_command != cmd else ''
                self.stdout.write(
                    self.style.ERROR(f'✗ {cmd}: {info["description"]} - NOT FOUND{command_info}')
                )
        
        if not missing:
            self.stdout.write(
                self.style.SUCCESS('\n✅ All media processing dependencies are available!')
            )
            return
        
        self.stdout.write(
            self.style.WARNING(f'\n⚠️  {len(missing)} dependencies are missing.')
        )
        
        if options['install']:
            target_platform = options['platform']
            self.stdout.write(
                self.style.HTTP_INFO(f'\nInstallation instructions for {target_platform.title()}:')
            )
            self.stdout.write('-' * 60)
            
            for cmd, info in missing:
                self.stdout.write(f'\n{cmd.upper()}: {info["description"]}')
                self.stdout.write(f'Required for: {", ".join(info["required_for"])}')
                
                if target_platform in info:
                    self.stdout.write(
                        self.style.SUCCESS(f'Install: {info[target_platform]}')
                    )
                elif 'note' in info:
                    self.stdout.write(
                        self.style.WARNING(f'Note: {info["note"]}')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING('Installation instructions not available for this platform')
                    )
                self.stdout.write('')
        
        else:
            self.stdout.write(
                self.style.HTTP_INFO('\nRun with --install --platform=<your_platform> for installation instructions.')
            )
        
        # Show what will be affected
        self.stdout.write(self.style.HTTP_INFO('\nImpact of missing dependencies:'))
        for cmd, info in missing:
            self.stdout.write(f'• Without {cmd}: {", ".join(info["required_for"])} will not work')
        
        self.stdout.write(
            self.style.WARNING('\nNote: Media uploads will still work, but processing will be skipped.')
        )