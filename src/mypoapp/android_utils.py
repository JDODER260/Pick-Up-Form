import os
import sys
from pathlib import Path
import asyncio
from datetime import datetime

# Check if we're on Android
try:
    from android.permissions import Permission, request_permissions, check_permission
    from android.storage import app_storage_path, primary_external_storage_path

    ANDROID = True
except ImportError:
    ANDROID = False
    app_storage_path = None
    primary_external_storage_path = None


class AndroidAPKInstaller:
    """Complete APK installation handler for Android"""

    @staticmethod
    async def request_install_permissions():
        """Request all necessary permissions for APK installation"""
        if not ANDROID:
            return True

        permissions_needed = []

        # Storage permissions
        try:
            if not check_permission(Permission.WRITE_EXTERNAL_STORAGE):
                permissions_needed.append(Permission.WRITE_EXTERNAL_STORAGE)
            if not check_permission(Permission.READ_EXTERNAL_STORAGE):
                permissions_needed.append(Permission.READ_EXTERNAL_STORAGE)
        except:
            pass

        # Install permission (Android 8.0+)
        try:
            if not check_permission(Permission.REQUEST_INSTALL_PACKAGES):
                permissions_needed.append(Permission.REQUEST_INSTALL_PACKAGES)
        except:
            pass

        if permissions_needed:
            result = await request_permissions(permissions_needed)
            return all(result.values()) if isinstance(result, dict) else bool(result)

        return True

    @staticmethod
    def _try_auto_install_apk(self, apk_path):
        """
        Try to install the APK programmatically.
        Returns (True, None) on success (installer Intent launched).
        Returns (False, error_message) on failure.
        """
        if not ANDROID:
            return False, "Not running on Android"

        try:
            # Android imports
            from android import mActivity
            from android.content import Intent
            from android.net import Uri
            from java.io import File
        except Exception as e:
            return False, f"Cannot import Android APIs: {e}"

        try:
            apk_file = File(apk_path)

            if not apk_file.exists():
                return False, f"APK file not found: {apk_path}"

            # Try to use FileProvider (for Android 7.0+)
            uses_fileprovider = False
            try:
                # Get package name for authority
                package_name = mActivity.getPackageName()
                authority = f"{package_name}.fileprovider"

                # Try to import FileProvider via jnius
                from jnius import autoclass
                FileProvider = autoclass('androidx.core.content.FileProvider')

                # Get content URI via FileProvider
                content_uri = FileProvider.getUriForFile(
                    mActivity,
                    authority,
                    apk_file
                )
                uri = content_uri
                uses_fileprovider = True
            except Exception as e:
                print(f"FileProvider not available, using file:// URI: {e}")
                # Fallback to file:// URI (may not work on Android 7.0+)
                uri = Uri.fromFile(apk_file)
                uses_fileprovider = False

            # Check Android version
            from jnius import autoclass
            Build = autoclass('android.os.Build')
            VERSION = autoclass('android.os.Build$VERSION')

            api_level = VERSION.SDK_INT

            # For Android 8.0+ (API 26+), need to request install permission
            if api_level >= 26:
                try:
                    PackageManager = autoclass('android.content.pm.PackageManager')
                    pm = mActivity.getPackageManager()

                    # Check if we have permission to install unknown apps
                    can_install = pm.canRequestPackageInstalls()

                    if not can_install:
                        # Need to request permission
                        try:
                            # Try to open settings for unknown sources
                            Settings = autoclass('android.provider.Settings')
                            intent = Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
                            intent.setData(Uri.parse(f"package:{package_name}"))
                            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            mActivity.startActivity(intent)
                            return False, "Please enable 'Install unknown apps' permission for this app"
                        except Exception as e:
                            return False, f"Cannot open permission settings: {e}"
                except Exception as e:
                    print(f"Error checking install permission: {e}")

            # Create install intent
            install_intent = Intent(Intent.ACTION_INSTALL_PACKAGE)
            install_intent.setData(uri)

            # Set flags
            if uses_fileprovider:
                install_intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

            install_intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

            # Optional: Set these extras for better UX
            install_intent.putExtra(Intent.EXTRA_NOT_UNKNOWN_SOURCE, True)
            install_intent.putExtra(Intent.EXTRA_RETURN_RESULT, True)

            # Optional: Add notification
            install_intent.putExtra(Intent.EXTRA_INSTALLER_PACKAGE_NAME, package_name)

            # Start installation
            mActivity.startActivity(install_intent)
            return True, None

        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, f"Installation error: {e}"

    @staticmethod
    async def install_apk_async(apk_path):
        """Async wrapper for APK installation"""
        loop = asyncio.get_event_loop()
        installer = AndroidAPKInstaller()

        # Request permissions first
        granted = await installer.request_install_permissions()
        if not granted:
            return False, "Required permissions not granted"

        # Run installation in executor since it might block
        return await loop.run_in_executor(
            None,
            lambda: installer._try_auto_install_apk(installer, apk_path)
        )


class DownloadManager:
    """Handle file downloads with progress"""

    @staticmethod
    def get_download_directory():
        """Get the appropriate download directory"""
        if ANDROID:
            try:
                # Try standard Downloads directory
                downloads = Path(primary_external_storage_path()) / "Download"
                if downloads.exists():
                    return downloads

                # Fallback to app-specific directory
                app_dir = Path(app_storage_path())
                downloads_dir = app_dir / "downloads"
                downloads_dir.mkdir(exist_ok=True)
                return downloads_dir
            except Exception as e:
                print(f"Error getting download directory: {e}")

        # Desktop fallback
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