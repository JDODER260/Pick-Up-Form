from pathlib import Path
from datetime import datetime

class DownloadManager:
    """Handle file downloads with progress"""

    @staticmethod
    def get_download_directory():
        """Get the appropriate download directory"""
        return Path.home() / "Downloads"

    @staticmethod
    async def download_file(url, progress_callback=None):
        """Download file with progress tracking"""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Get filename from URL or headers
                async with client.stream('GET', url) as response:
                    response.raise_for_status()

                    # Get filename
                    filename = None

                    # Try Content-Disposition header
                    content_disposition = response.headers.get('Content-Disposition', '')
                    if 'filename=' in content_disposition:
                        filename = content_disposition.split('filename=')[1].strip('"\'')

                    # Fallback to URL path
                    if not filename:
                        filename = Path(url).name

                    # Fallback to timestamp
                    if not filename or filename == '':
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename = f"download_{timestamp}.bin"

                    # Get total size for progress
                    total_size = int(response.headers.get('content-length', 0))

                    # Save to download directory
                    download_dir = DownloadManager.get_download_directory()
                    filepath = download_dir / filename

                    downloaded = 0
                    with open(filepath, 'wb') as f:
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            f.write(chunk)
                            downloaded += len(chunk)

                            # Report progress
                            if progress_callback and total_size > 0:
                                progress = (downloaded / total_size) * 100
                                await progress_callback(progress)

                    return str(filepath), None

        except Exception as e:
            return None, str(e)