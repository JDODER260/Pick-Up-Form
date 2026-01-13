import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW, CENTER
import json
import os, sys
from datetime import datetime
import requests
import uuid
import re
from packaging import version
import threading
import asyncio
from typing import Dict, List, Optional
import webbrowser
from pathlib import Path
import tempfile
import textwrap
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from io import BytesIO
from .android_utils import AndroidAPKInstaller, DownloadManager, ANDROID


def is_android():
    """Detect if running on Android in Chaquopy/Toga 5.3"""
    # Chaquopy sets specific environment variables
    if 'CHAQUOPY' in os.environ:
        return True

    # Check for Chaquopy in Python path
    for path in sys.path:
        if 'chaquopy' in str(path).lower():
            return True

    # Check for Android app directory
    if '/data/data/' in os.path.abspath('.'):
        return True

    return False


ANDROID = is_android()
print(f"Running on Android (Chaquopy): {ANDROID}")

# Chaquopy-specific imports
if ANDROID:
    try:
        # Chaquopy uses jnius for Android API access
        from jnius import autoclass, cast

        print("✓ Successfully imported jnius for Chaquopy")

        # Get Android context
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        mActivity = PythonActivity.mActivity

        # Import successful
        ANDROID_IMPORTS_WORKING = True

    except ImportError as e:
        print(f"✗ Cannot import jnius: {e}")
        ANDROID_IMPORTS_WORKING = False
        mActivity = None
else:
    ANDROID_IMPORTS_WORKING = False
    mActivity = None


class POApp(toga.App):
    def __init__(self):
        super().__init__(
            formal_name="Pick Up & Delivery",
            app_id="com.doublersharpening.mypoapp"
        )
        # Existing URLs
        self.upload_url = "https://doublersharpening.com/api/upload_po/"
        self.update_check_url = "https://doublersharpening.com/media/mypoapp/"
        self.company_db_url = "https://doublersharpening.com/api/company_db/"

        # New URL for delivery data
        self.delivery_url = "https://doublersharpening.com/api/delivery_pos/"
        self.delivery_url = "https://doublersharpening.com/api/delivery_pos/"

        # Use appropriate base directory for Android

        self.pdf_base_dir = "/storage/emulated/0/download/PickUpForms"

        self.current_version = "2.2.7"  # Updated version for new features

        # Data storage
        self.data_dir = None
        self.data_file = None
        self.settings_file = None
        self.company_db_file = None
        self.delivery_data_file = None
        self.route_label = None

        # App state
        self.selected_route = ""
        self.selected_company = ""
        self.driver_id = ""
        self.app_mode = "delivery"  # Default to delivery mode: "delivery" or "pickup"

        # Theme state (light/dark/system) and brand colors
        self.theme_preference = "system"  # "system" | "light" | "dark"
        self.brand_red = "#D10024"
        self.brand_blue = "#004b88"
        self.bg_color = "white"
        self.text_color = "black"
        self.accent_color = self.brand_blue

        # Company database structure
        self.company_database = {}
        self.available_routes = []
        self.company_names = []
        self.frequent_blades = []

        # Delivery data structure - NEW: store API response directly
        self.delivery_api_response = {}  # Store full API response
        self.delivery_companies = []  # List of company names from delivery data
        self.current_delivery_index = 0
        self.total_deliveries = 0

        self.delivery_po_list_box = None

        # Updated main display order
        self.display_order = ["uploaded", "description", "company", "route"]

        print("POApp initialized with delivery mode")

    def startup(self):
        # Initialize paths
        self.data_dir = self.paths.data
        self.data_file = os.path.join(self.data_dir, "po_data.json")
        self.settings_file = os.path.join(self.data_dir, "app_settings.json")
        self.company_db_file = os.path.join(self.data_dir, "company_database.json")
        self.delivery_data_file = os.path.join(self.data_dir, "delivery_data.json")

        os.makedirs(self.data_dir, exist_ok=True)

        # Load data
        self.load_settings()
        self.load_company_database()
        self.load_delivery_data()

        print(f"Loaded {len(self.available_routes)} routes")
        print(f"Running on Android: {ANDROID}")
        # AUTO SYNC ON STARTUP
        self.sync_company_database_on_startup()

        # Generate driver ID if needed
        if not self.driver_id:
            self.driver_id = str(uuid.uuid4())[:8]
            self.save_settings()

        # Create main window
        self.main_window = toga.MainWindow(title=f"Pick Up & Delivery v{self.current_version}")

        # Create screens
        self.route_selection_screen = self.create_route_selection_screen()
        self.company_management_screen = self.create_company_management_screen()
        self.settings_screen = self.create_settings_screen()

        # Create mode-specific screens
        self.delivery_home_screen = self.create_delivery_home_screen()
        self.pickup_home_screen = self.create_pickup_home_screen()
        self.add_po_screen = self.create_add_po_screen()

        # Apply current theme to screens
        self.apply_theme(self.theme_preference)

        # Set initial screen based on mode
        if not self.selected_route:
            self.main_window.content = self.route_selection_screen
        else:
            self.main_window.content = self.delivery_home_screen if self.app_mode == "delivery" else self.pickup_home_screen
            # Ensure data is loaded/rendered on first paint; otherwise pickup list can appear empty
            # until the user navigates away/back.
            if self.app_mode == "pickup":
                self.load_pos()
                if hasattr(self, 'selection_label'):
                    selection_text = f"{self.selected_route}"
                    if self.selected_company:
                        selection_text += f" | {self.selected_company}"
                    self.selection_label.text = selection_text
            else:
                self.update_delivery_display()
        print(f"Platform: {sys.platform}")
        print(f"Python version: {sys.version}")
        print(f"Toga version: {toga.__version__}")

        # Check all possible Android indicators
        android_indicators = {
            'sys.platform contains "linux"': 'linux' in sys.platform,
            'ANDROID_ROOT in os.environ': 'ANDROID_ROOT' in os.environ,
            'ANDROID_DATA in os.environ': 'ANDROID_DATA' in os.environ,
            'PYTHONHOME contains "android"': 'android' in os.environ.get('PYTHONHOME', ''),
        }

        print("Android detection indicators:")
        for key, value in android_indicators.items():
            print(f"  {key}: {value}")

        print(f"Final ANDROID flag: {ANDROID}")
        self.main_window.show()

        # Enable Android hardware back button handling
        try:
            if ANDROID:
                self.enable_android_back()
        except Exception as e:
            print(f"Failed to enable Android back handling: {e}")

    def create_delivery_home_screen(self):
        """Create delivery mode home screen"""
        main_box = toga.Box(style=Pack(direction=COLUMN, padding=10))

        # Header with mode switch
        header_box = toga.Box(style=Pack(direction=ROW, padding_bottom=10))

        mode_label = toga.Label(
            "DELIVERY MODE",
            style=Pack(flex=1, font_size=20, font_weight="bold", color="#2E7D32")
        )

        switch_btn = toga.Button(
            "Switch to Pickup",
            on_press=self.switch_to_pickup_mode,
            style=Pack(width=150, height=60, background_color="#FF9800")
        )

        header_box.add(mode_label)
        header_box.add(switch_btn)

        # Route/Company info
        info_box = toga.Box(style=Pack(direction=COLUMN, padding=10, background_color="#E8F5E9"))

        self.route_label = toga.Label(
            f"Route: {self.selected_route if self.selected_route else 'Not Selected'}",
            style=Pack(font_size=16, padding_bottom=5)
        )

        deliveries_label = toga.Label(
            f"Deliveries Loaded: {self.total_deliveries}",
            style=Pack(font_size=16, padding_bottom=5)
        )

        info_box.add(self.route_label)
        info_box.add(deliveries_label)

        # Action buttons
        action_box = toga.Box(style=Pack(direction=COLUMN, padding=10))

        # Row 1: Download and Company Selection
        row1 = toga.Box(style=Pack(direction=ROW, padding_bottom=5))

        download_btn = toga.Button(
            "Download Route",
            on_press=self.download_delivery_route,
            style=Pack(flex=1, padding=5, background_color="#2196F3")
        )

        select_company_btn = toga.Button(
            "Select Route",
            on_press=self.show_route_selection,
            style=Pack(flex=1, padding=5, background_color="#2196F3")
        )

        row1.add(download_btn)
        row1.add(select_company_btn)

        # Row 2: Print and Navigation
        row2 = toga.Box(style=Pack(direction=ROW, padding_bottom=5))

        print_btn = toga.Button(
            "Print Receipt",
            on_press=self.print_current_receipt,
            style=Pack(flex=1, padding=5, background_color="#4CAF50")
        )

        prev_btn = toga.Button(
            "Previous",
            on_press=self.previous_delivery,
            style=Pack(flex=1, padding=5)
        )

        next_btn = toga.Button(
            "Next",
            on_press=self.next_delivery,
            style=Pack(flex=1, padding=5)
        )

        row2.add(print_btn)
        row2.add(prev_btn)
        row2.add(next_btn)

        # Create the delivery display box
        self.delivery_display_box = toga.Box(
            style=Pack(direction=COLUMN, padding=20, background_color="#F5F5F5")
        )

        # Wrap it in a ScrollContainer with fixed height
        self.delivery_scroll_container = toga.ScrollContainer(
            content=self.delivery_display_box,
            style=Pack(height=400)  # Fixed height of 400 pixels - this works in Toga 5.2
        )

        # Or if you want it to fill available space but not exceed screen:
        # Use a fixed height that works for most screens
        self.delivery_scroll_container = toga.ScrollContainer(
            content=self.delivery_display_box,
            style=Pack(height=300)  # 300px is a good default for mobile
        )

        action_box.add(row1)
        action_box.add(row2)

        # Settings button
        settings_btn = toga.Button(
            "Settings",
            on_press=self.show_settings,
            style=Pack(padding=10)
        )

        main_box.add(header_box)
        main_box.add(info_box)
        main_box.add(action_box)
        main_box.add(self.delivery_scroll_container)
        main_box.add(settings_btn)

        # Update display
        self.update_delivery_display()

        return main_box

    def create_pickup_home_screen(self):
        """Create pickup mode home screen (modified from original)"""
        main_box = toga.Box(style=Pack(direction=COLUMN, padding=10))

        # Header with mode switch
        header_box = toga.Box(style=Pack(direction=ROW, padding_bottom=10))

        mode_label = toga.Label(
            "PICKUP MODE",
            style=Pack(flex=1, font_size=20, font_weight="bold", color="#FF9800")
        )

        switch_btn = toga.Button(
            "Switch to Delivery",
            on_press=self.switch_to_delivery_mode,
            style=Pack(width=150, height=60, background_color="#2E7D32")
        )

        header_box.add(mode_label)
        header_box.add(switch_btn)

        # Display current selections
        selection_text = f"{self.selected_route}"
        if self.selected_company:
            selection_text += f" | {self.selected_company}"

        self.selection_label = toga.Label(
            selection_text,
            style=Pack(font_size=16, padding_bottom=10)
        )

        # Change buttons
        button_box = toga.Box(style=Pack(direction=ROW, padding_bottom=10))
        change_route_btn = toga.Button(
            "Change Route",
            on_press=self.show_route_selection,
            style=Pack(flex=1, padding=5)
        )
        change_company_btn = toga.Button(
            "Change Company",
            on_press=self.show_company_selection,
            style=Pack(flex=1, padding=5)
        )
        button_box.add(change_route_btn)
        button_box.add(change_company_btn)

        # PO List
        self.po_list_box = toga.Box(style=Pack(direction=COLUMN, flex=1))
        po_scroll = toga.ScrollContainer(
            content=self.po_list_box,
            style=Pack(flex=1)
        )

        # Action buttons (removed refresh button)
        action_box = toga.Box(style=Pack(direction=COLUMN, padding_top=10))

        row1 = toga.Box(style=Pack(direction=ROW, padding_bottom=5))
        row2 = toga.Box(style=Pack(direction=ROW))

        add_btn = toga.Button("Add New", on_press=self.show_add_po, style=Pack(flex=1, padding=5))
        upload_btn = toga.Button("Upload", on_press=self.upload_selected, style=Pack(flex=1, padding=5))
        delete_btn = toga.Button("Delete", on_press=self.delete_selected, style=Pack(flex=1, padding=5))

        select_all_btn = toga.Button("Select All", on_press=self.select_all_pos, style=Pack(flex=1, padding=5))
        update_btn = toga.Button("Update", on_press=self.update_selected, style=Pack(flex=1, padding=5))
        settings_btn = toga.Button("Settings", on_press=self.show_settings, style=Pack(flex=1, padding=5))
        # No refresh button - replaced with mode switch

        row1.add(add_btn)
        row1.add(upload_btn)
        row1.add(delete_btn)

        row2.add(select_all_btn)
        row2.add(update_btn)
        row2.add(settings_btn)
        # Leave empty space where refresh button was

        action_box.add(row1)
        action_box.add(row2)

        # Compose layout
        main_box.add(header_box)
        main_box.add(self.selection_label)
        main_box.add(button_box)
        main_box.add(po_scroll)
        main_box.add(action_box)

        return main_box

    def switch_to_delivery_mode(self, widget):
        """Switch from pickup to delivery mode"""
        self.app_mode = "delivery"
        self.save_settings()
        self.main_window.content = self.delivery_home_screen
        self.update_delivery_display()

        if hasattr(self, 'selection_label'):
            selection_text = f"{self.selected_route}"
            if self.selected_company:
                selection_text += f" | {self.selected_company}"
            self.selection_label.text = selection_text
            route_label = f"Route: {self.selected_route if self.selected_route else 'Not Selected'}"

            self.route_label.text = route_label

    def switch_to_pickup_mode(self, widget):
        """Switch from delivery to pickup mode"""
        self.app_mode = "pickup"
        self.save_settings()
        self.main_window.content = self.pickup_home_screen
        self.load_pos()

        if hasattr(self, 'selection_label'):
            selection_text = f"{self.selected_route}"
            if self.selected_company:
                selection_text += f" | {self.selected_company}"
            self.selection_label.text = selection_text
            route_label = f"Route: {self.selected_route if self.selected_route else 'Not Selected'}"

            self.route_label.text = route_label

    def download_delivery_route(self, widget):
        """Download delivery route data for selected route"""
        if not self.selected_route:
            self.show_dialog_async("error", "No Route", "Please select a route first")
            return

        async def download_task():
            try:
                print(f"Downloading delivery data for route: {self.selected_route}")

                # Construct API URL with route parameter
                api_url = f"{self.delivery_url}?route={self.selected_route}"

                response = requests.get(api_url, timeout=30)

                if response.status_code == 200:
                    api_response = response.json()
                    print(f"DEBUG: Full API response: {json.dumps(api_response, indent=2)}")

                    # Check if API call was successful
                    if api_response.get("success"):
                        # Save the full API response
                        with open(self.delivery_data_file, 'w') as f:
                            json.dump(api_response, f, indent=2)

                        self.delivery_api_response = api_response

                        # Extract company names from data
                        if "data" in api_response:
                            data_field = api_response["data"]

                            # Check if data is a dictionary
                            if isinstance(data_field, dict):
                                self.delivery_companies = list(data_field.keys())
                                self.total_deliveries = len(self.delivery_companies)
                                self.current_delivery_index = 0

                                print(f"Downloaded {self.total_deliveries} deliveries for route {self.selected_route}")
                                print(f"Companies: {self.delivery_companies}")

                                # Update display
                                self.update_delivery_display()

                                await self.main_window.dialog(
                                    toga.InfoDialog(
                                        title="Success",
                                        message=f"Downloaded {self.total_deliveries} deliveries for route {self.selected_route}"
                                    )
                                )
                            else:
                                error_msg = f"Expected 'data' to be a dictionary, got {type(data_field)}"
                                print(f"ERROR: {error_msg}")
                                await self.main_window.dialog(
                                    toga.ErrorDialog(
                                        title="Data Format Error",
                                        message=f"API returned wrong data format: {error_msg}"
                                    )
                                )
                        else:
                            await self.main_window.dialog(
                                toga.ErrorDialog(
                                    title="Error",
                                    message="No 'data' field in API response"
                                )
                            )
                    else:
                        await self.main_window.dialog(
                            toga.ErrorDialog(
                                title="Error",
                                message=f"API returned error: {api_response.get('error', 'Unknown error')}"
                            )
                        )
                else:
                    await self.main_window.dialog(
                        toga.ErrorDialog(
                            title="Error",
                            message=f"Server returned status: {response.status_code}\nResponse: {response.text[:200]}"
                        )
                    )

            except Exception as e:
                print(f"Error downloading delivery data: {e}")
                import traceback
                traceback.print_exc()
                await self.main_window.dialog(
                    toga.ErrorDialog(
                        title="Error",
                        message=f"Failed to download: {str(e)}"
                    )
                )

        asyncio.create_task(download_task())

    def load_delivery_data(self):
        """Load delivery data from file"""
        try:
            if os.path.exists(self.delivery_data_file):
                with open(self.delivery_data_file, 'r') as f:
                    self.delivery_api_response = json.load(f)

                # Extract company names from data
                if "data" in self.delivery_api_response:
                    self.delivery_companies = list(self.delivery_api_response["data"])
                    self.total_deliveries = len(self.delivery_companies)
                    print(f"Loaded {self.total_deliveries} deliveries from file")
                else:
                    self.delivery_companies = []
                    self.total_deliveries = 0
                    print("No delivery data found in file")
            else:
                self.delivery_api_response = {}
                self.delivery_companies = []
                self.total_deliveries = 0
                print("No delivery data file found")
        except Exception as e:
            print(f"Error loading delivery data: {e}")
            self.delivery_api_response = {}
            self.delivery_companies = []
            self.total_deliveries = 0

    def update_delivery_display(self):
        """Update the delivery information display"""
        if not hasattr(self, 'delivery_display_box'):
            return

        self.delivery_display_box.clear()

        if self.total_deliveries == 0:
            no_data_label = toga.Label(
                "No deliveries loaded. Press 'Download Route' to fetch delivery data.",
                style=Pack(padding=20, text_align=CENTER)
            )
            self.delivery_display_box.add(no_data_label)
            return

        # Get current delivery
        if self.current_delivery_index < self.total_deliveries:
            current_company = self.delivery_companies[self.current_delivery_index]

            # DEBUG: Check the structure of delivery_api_response
            print(f"DEBUG: API response keys: {list(self.delivery_api_response.keys())}")
            print(f"DEBUG: Looking for company: {current_company}")

            # Check if 'data' exists and is the right type
            if "data" not in self.delivery_api_response:
                error_label = toga.Label(
                    "Error: No 'data' field in API response",
                    style=Pack(padding=20, text_align=CENTER, color="red")
                )
                self.delivery_display_box.add(error_label)
                return

            data_field = self.delivery_api_response["data"]
            print(f"DEBUG: Type of 'data' field: {type(data_field)}")

            # Handle different types of 'data' field
            if isinstance(data_field, str):
                # 'data' is a string, not a dictionary
                error_label = toga.Label(
                    f"Error: 'data' field is a string: {data_field[:100]}...",
                    style=Pack(padding=20, text_align=CENTER, color="red")
                )
                self.delivery_display_box.add(error_label)
                return

            elif isinstance(data_field, dict):
                # This is what we expect
                if current_company in data_field:
                    company_data = data_field[current_company]
                else:
                    # Company not found in data
                    error_label = toga.Label(
                        f"Error: Company '{current_company}' not found in data",
                        style=Pack(padding=20, text_align=CENTER, color="red")
                    )
                    self.delivery_display_box.add(error_label)
                    return
            else:
                # Unexpected type
                error_label = toga.Label(
                    f"Error: 'data' field has unexpected type: {type(data_field)}",
                    style=Pack(padding=20, text_align=CENTER, color="red")
                )
                self.delivery_display_box.add(error_label)
                return

            # Update selected company
            self.selected_company = current_company
            self.save_settings()

            # Create display
            index_label = toga.Label(
                f"Delivery {self.current_delivery_index + 1} of {self.total_deliveries}",
                style=Pack(font_size=18, font_weight="bold", padding_bottom=10)
            )

            company_label = toga.Label(
                f"Company: {current_company}",
                style=Pack(font_size=16, padding_bottom=5)
            )

            self.delivery_display_box.add(index_label)
            self.delivery_display_box.add(company_label)

            # Show each PO for this company
            for i, po_item in enumerate(company_data):
                if i > 0:
                    # Add separator between POs
                    separator = toga.Label("─" * 40, style=Pack(padding_top=10, padding_bottom=10))
                    self.delivery_display_box.add(separator)

                # PO Number
                if "po_number" in po_item:
                    po_label = toga.Label(
                        f"PO #: {po_item['po_number']}",
                        style=Pack(font_size=14, font_weight="bold", padding_bottom=5)
                    )
                    self.delivery_display_box.add(po_label)

                # Description
                if "description" in po_item:
                    desc_label = toga.Label(
                        f"Description: {po_item['description']}",
                        style=Pack(font_size=14, padding_bottom=3)
                    )
                    self.delivery_display_box.add(desc_label)

                # Quantity
                if "quantity" in po_item:
                    qty_label = toga.Label(
                        f"Quantity: {po_item['quantity']}",
                        style=Pack(font_size=14, padding_bottom=3)
                    )
                    self.delivery_display_box.add(qty_label)

                # Pickup Date
                if "pickup_date" in po_item:
                    pickup_label = toga.Label(
                        f"Pickup Date: {po_item['pickup_date']}",
                        style=Pack(font_size=14, padding_bottom=3)
                    )
                    self.delivery_display_box.add(pickup_label)

                # Expected Delivery
                if "expected_delivery" in po_item and po_item["expected_delivery"] != "N/A":
                    expected_label = toga.Label(
                        f"Expected: {po_item['expected_delivery']}",
                        style=Pack(font_size=14, padding_bottom=3)
                    )
                    self.delivery_display_box.add(expected_label)

    def previous_delivery(self, widget):
        """Navigate to previous delivery"""
        if self.total_deliveries == 0:
            return

        self.current_delivery_index = (self.current_delivery_index - 1) % self.total_deliveries
        self.update_delivery_display()

    def next_delivery(self, widget):
        """Navigate to next delivery"""
        if self.total_deliveries == 0:
            return

        self.current_delivery_index = (self.current_delivery_index + 1) % self.total_deliveries
        self.update_delivery_display()

    def generate_simple_pdf_receipt(self, company_name, po_items):
        """Generate a simpler PDF receipt optimized for mobile and half-letter printing"""
        try:
            current_date = datetime.now().strftime("%Y-%m-%d")
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            # Create folder structure
            route_folder = os.path.join(self.pdf_base_dir, self.selected_route)
            date_folder = os.path.join(route_folder, current_date)
            os.makedirs(date_folder, exist_ok=True)

            # Create safe filename
            safe_company = "".join(c for c in company_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            pdf_filename = f"receipt_{safe_company}_{timestamp}.pdf"
            pdf_path = os.path.join(date_folder, pdf_filename)

            # ===== HALF-LETTER SIZE =====
            # Half-letter: 5.5 x 8.5 inches (139.7 x 215.9 mm)
            # Convert to points: 1 inch = 72 points
            half_letter_width = 5.5 * inch
            half_letter_height = 8.5 * inch

            # Smaller margins for half-letter
            left_margin = 0.25 * inch
            right_margin = 0.25 * inch
            top_margin = 0.25 * inch
            bottom_margin = 0.25 * inch

            # Create PDF using half-letter size
            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=(half_letter_width, half_letter_height),
                leftMargin=left_margin,
                rightMargin=right_margin,
                topMargin=top_margin,
                bottomMargin=bottom_margin
            )

            styles = getSampleStyleSheet()
            elements = []

            # ===== HEADER =====
            # Title - smaller font for half-letter
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=12,  # Smaller for half-letter
                alignment=1,  # Center
                spaceAfter=8  # Less spacing
            )
            elements.append(Paragraph("DOUBLE R SHARPENING", title_style))

            # Contact info - smaller font
            contact_style = ParagraphStyle(
                'Contact',
                parent=styles['Normal'],
                fontSize=7,  # Smaller for half-letter
                alignment=1,
                spaceAfter=4  # Less spacing
            )
            contact_text = "Phone: 814-333-1181 | Email: office@doublersharpening.com"
            elements.append(Paragraph(contact_text, contact_style))

            # Website on separate line
            website_style = ParagraphStyle(
                'Website',
                parent=styles['Normal'],
                fontSize=7,
                alignment=1,
                spaceAfter=12
            )
            elements.append(Paragraph("Website: https://doublersharpening.com", website_style))

            # ===== COMPANY INFO =====
            styles = getSampleStyleSheet()
            small_style = styles["Normal"]
            small_style.fontName = "Helvetica"
            small_style.fontSize = 8

            info_col_widths = [0.8 * inch, 1.2 * inch, 0.8 * inch, 1.2 * inch]
            print(po_items[0])
            info_data = [
                [
                    "Company:",
                    Paragraph(company_name, small_style),  # <-- use Paragraph here
                    "Pickup:",
                    po_items[0]['pickup_date'] if po_items else current_date
                ],
                [
                    "Delivery:",
                    current_date,
                    "Custom:",
                    "_________________"
                ]
            ]

            info_table = Table(info_data, colWidths=info_col_widths)
            info_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                ('BACKGROUND', (2, 0), (2, -1), colors.lightgrey),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),  # optional: top-align for multi-line cells
            ]))

            elements.append(info_table)
            elements.append(Spacer(1, 10))

            # ===== TABLE DATA =====
            table_data = []
            headers = ["Qty Rec", "Qty Ship", "Back Order", "Description", "Hammer", "Re-tip", "New Tip", "No Service"]
            table_data.append(headers)

            for item in po_items:
                blade_details = item.get('blade_details', {})

                # Extract values
                qty_rec = blade_details.get('received_qty', '0')
                qty_ship = blade_details.get('shipped_qty', '0')
                back_order = blade_details.get('back_order', '0')
                description = item.get('description', '')
                hammer = blade_details.get('hammer', '0')
                re_tip = blade_details.get('re_tipped', '0')
                new_tip = blade_details.get('new_tip_no', '0')
                no_service = blade_details.get('no_service', '0')

                # Clean values for display
                qty_rec_display = qty_rec if qty_rec not in ['None', ''] else '0'
                qty_ship_display = qty_ship if qty_ship not in ['None', ''] else '0'
                back_order_display = back_order if back_order not in ['None', ''] else '0'

                # Truncate description to fit better
                description_display = description[:30] + ('...' if len(description) > 30 else '')

                hammer_display = hammer[:3] if hammer not in ['None', ''] else '0'
                re_tip_display = re_tip[:3] if re_tip not in ['None', ''] else '0'
                new_tip_display = new_tip[:3] if new_tip not in ['None', ''] else '0'
                no_service_display = no_service[:3] if no_service not in ['None', ''] else '0'

                table_data.append([
                    qty_rec_display,
                    qty_ship_display,
                    back_order_display,
                    description_display,
                    hammer_display,
                    re_tip_display,
                    new_tip_display,
                    no_service_display
                ])

            # Create table with adjusted column widths
            col_widths = [
                0.4 * inch,  # Qty Rec
                0.4 * inch,  # Qty Ship
                0.6 * inch,  # Back Order
                1.5 * inch,  # Description (wider for text)
                0.4 * inch,  # Hammer
                0.4 * inch,  # Re-tip
                0.4 * inch,  # New Tip
                0.5 * inch  # No Service
            ]

            table = Table(table_data, colWidths=col_widths, repeatRows=1)

            # Style the table with word wrapping and different font sizes
            style_commands = [
                # Header styling
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),

                # Cell alignment
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('ALIGN', (3, 1), (3, -1), 'LEFT'),  # Description left aligned

                # Font sizes - description column smaller
                ('FONTSIZE', (0, 1), (2, -1), 8),  # Columns 0-2: size 8
                ('FONTSIZE', (3, 1), (3, -1), 6),  # Column 3 (Description): size 6 (0.75 of 8)
                ('FONTSIZE', (4, 1), (-1, -1), 8),  # Columns 4-7: size 8
                ('FONTSIZE', (0, 0), (-1, 0), 7),  # Header row: size 7

                # Enable word wrapping for all cells
                ('WORDWRAP', (0, 0), (-1, -1), True),

                # Row height for multi-line text
                ('LEADING', (0, 0), (-1, -1), 9),  # Line spacing
                ('TOPPADDING', (0, 0), (-1, -1), 2),  # Top padding
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),  # Bottom padding

                # Header padding
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),

                # Grid for ALL cells
                ('BOX', (0, 0), (-1, -1), 0.25, colors.black),
                ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.black),
            ]

            # Add column borders
            for i in range(len(col_widths)):
                style_commands.append(('LINEAFTER', (i, 0), (i, -1), 0.25, colors.black))

            table.setStyle(TableStyle(style_commands))

            elements.append(table)
            elements.append(Spacer(1, 15))  # Less spacing

            # ===== SIGNATURE SECTION =====
            signature_style = ParagraphStyle(
                'Signature',
                parent=styles['Normal'],
                fontSize=9,  # Slightly smaller
                spaceBefore=10  # Less spacing
            )

            elements.append(Paragraph("Delivery Signature: _________________________", signature_style))
            elements.append(Spacer(1, 5))

            # ===== FOOTER =====
            footer_style = ParagraphStyle(
                'Footer',
                parent=styles['Normal'],
                fontSize=7,  # Smaller
                fontName='Helvetica-Oblique',
                alignment=1,
                spaceBefore=15  # Less spacing
            )

            footer_text = f"Generated: {current_date} | Route: {self.selected_route} | Driver: {self.driver_id}"
            elements.append(Paragraph(footer_text, footer_style))

            # ===== HANDLE MULTIPLE PAGES =====
            # Build PDF
            doc.build(elements)

            return str(pdf_path)

        except Exception as e:
            print(f"Error generating simple PDF: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def print_current_receipt(self, widget):
        """Generate and save PDF receipt for current delivery"""
        if self.total_deliveries == 0:
            self.show_dialog_async("error", "No Data", "No deliveries loaded. Download route data first.")
            return

        if self.current_delivery_index >= self.total_deliveries:
            return

        # Request storage permission on Android
        if ANDROID:
            granted = await self.AndroidPermissions.request_storage_permission()
            if not granted:
                self.show_dialog_async("error", "Permission Required",
                                       "Storage permission is required to save PDF receipts.")
                return

        # Get current delivery data
        current_company = self.delivery_companies[self.current_delivery_index]
        company_data = self.delivery_api_response["data"][current_company]

        # Generate PDF using the simpler method
        pdf_path = self.generate_simple_pdf_receipt(current_company, company_data)

        if pdf_path:
            # Extract just the filename for display
            pdf_filename = Path(pdf_path).name
            route = self.selected_route
            date_folder = datetime.now().strftime("%Y-%m-%d")

            # Show success message
            self.show_dialog_async(
                "info",
                "PDF Generated Successfully",
                f"Receipt for {current_company} has been saved.\n\n"
                f"📁 Location:\n"
                f"{pdf_path}\n\n"
                f"📄 File: {pdf_filename}\n\n"
                "To print or share:\n"
                "1. Open your file manager\n"
                "2. Navigate to the folder above\n"
                "3. Tap the PDF file to open\n"
                "4. Use the print/share option"
            )
        else:
            self.show_dialog_async("error", "PDF Generation Failed", "Could not generate PDF receipt")

    def create_settings_screen(self):
        """Create settings screen with app mode option"""
        main_box = toga.Box(style=Pack(direction=COLUMN, padding=10))

        title = toga.Label("Settings", style=Pack(font_size=24, padding_bottom=10))

        # App Mode Selection
        mode_label = toga.Label("Default App Mode:", style=Pack(padding_bottom=5))
        mode_box = toga.Box(style=Pack(direction=ROW, padding_bottom=10))

        self.mode_delivery_radio = toga.Switch(
            "Delivery Mode",
            value=(self.app_mode == "delivery"),
            on_change=self.on_mode_change,
            style=Pack(padding_right=10)
        )

        self.mode_pickup_radio = toga.Switch(
            "Pickup Mode",
            value=(self.app_mode == "pickup"),
            on_change=self.on_mode_change,
            style=Pack(padding_left=10)
        )

        mode_box.add(self.mode_delivery_radio)
        mode_box.add(self.mode_pickup_radio)

        # Theme selection
        theme_label = toga.Label("Theme:", style=Pack(padding_top=10, padding_bottom=5))
        self.theme_selection = toga.Selection(
            items=["System", "Light", "Dark"],
            style=Pack(padding_bottom=10)
        )
        # set current value
        current_theme_label = {
            "system": "System",
            "light": "Light",
            "dark": "Dark",
        }.get(self.theme_preference, "System")
        self.theme_selection.value = current_theme_label

        def on_theme_change(widget):
            label_to_pref = {"System": "system", "Light": "light", "Dark": "dark"}
            pref = label_to_pref.get(widget.value, "system")
            self.apply_theme(pref)
            self.save_settings()
        self.theme_selection.on_change = on_theme_change

        # Company Database Management
        db_label = toga.Label("Company Database:", style=Pack(padding_bottom=5))
        manage_db_btn = toga.Button(
            "Manage Company Database",
            on_press=self.show_company_management,
            style=Pack(padding_bottom=10)
        )

        sync_db_btn = toga.Button(
            "Sync with Server",
            on_press=self.sync_company_db_ui,
            style=Pack(padding_bottom=10)
        )

        # App Info
        driver_label = toga.Label(f"Driver ID: {self.driver_id}", style=Pack(padding_bottom=5))
        route_label = toga.Label(f"Current Route: {self.selected_route}", style=Pack(padding_bottom=5))
        company_label = toga.Label(f"Current Company: {self.selected_company}", style=Pack(padding_bottom=5))
        version_label = toga.Label(f"Version: {self.current_version}", style=Pack(padding_bottom=10))

        # Update check
        update_btn = toga.Button(
            "Check for Updates",
            on_press=lambda w: self.check_for_updates(False),
            style=Pack(padding_bottom=10)
        )

        # URL settings
        url_label = toga.Label("Upload URL:", style=Pack(padding_bottom=5))
        self.url_input = toga.TextInput(
            value=self.upload_url,
            placeholder="API URL",
            style=Pack(padding_bottom=10)
        )

        db_url_label = toga.Label("Database URL:", style=Pack(padding_bottom=5))
        self.db_url_input = toga.TextInput(
            value=self.company_db_url,
            placeholder="Database URL",
            style=Pack(padding_bottom=10)
        )

        delivery_url_label = toga.Label("Delivery API URL:", style=Pack(padding_bottom=5))
        self.delivery_url_input = toga.TextInput(
            value=self.delivery_url,
            placeholder="Delivery API URL",
            style=Pack(padding_bottom=10)
        )

        # Action buttons
        button_box = toga.Box(style=Pack(direction=ROW, padding_top=10))

        save_btn = toga.Button(
            "Save",
            on_press=self.save_settings_from_ui,
            style=Pack(flex=1, padding_right=5)
        )

        back_btn = toga.Button(
            "Back",
            on_press=self.show_current_home,
            style=Pack(flex=1, padding_left=5)
        )

        button_box.add(save_btn)
        button_box.add(back_btn)

        main_box.add(title)
        main_box.add(mode_label)
        main_box.add(mode_box)
        main_box.add(theme_label)
        main_box.add(self.theme_selection)
        main_box.add(db_label)
        main_box.add(manage_db_btn)
        main_box.add(sync_db_btn)
        main_box.add(driver_label)
        main_box.add(route_label)
        main_box.add(company_label)
        main_box.add(version_label)
        main_box.add(update_btn)
        main_box.add(url_label)
        main_box.add(self.url_input)
        main_box.add(db_url_label)
        main_box.add(self.db_url_input)
        main_box.add(delivery_url_label)
        main_box.add(self.delivery_url_input)
        main_box.add(button_box)

        return main_box

    def on_mode_change(self, widget):
        """Handle app mode change"""
        if widget == self.mode_delivery_radio and widget.value:
            self.mode_pickup_radio.value = False
            self.app_mode = "delivery"
        elif widget == self.mode_pickup_radio and widget.value:
            self.mode_delivery_radio.value = False
            self.app_mode = "pickup"

    def save_settings_from_ui(self, widget):
        """Save settings from UI"""
        self.upload_url = self.url_input.value.strip()
        self.company_db_url = self.db_url_input.value.strip()
        self.delivery_url = self.delivery_url_input.value.strip()
        self.save_settings()
        self.show_dialog_async("info", "Success", "Settings saved")
        self.show_current_home()

    def show_current_home(self, widget=None):
        """Show the appropriate home screen based on mode"""
        if self.app_mode == "delivery":
            self.main_window.content = self.delivery_home_screen
            self.update_delivery_display()
        else:
            self.main_window.content = self.pickup_home_screen
            self.load_pos()

            # ADD THIS - Update the company display
            if hasattr(self, 'selection_label'):
                selection_text = f"{self.selected_route}"
                if self.selected_company:
                    selection_text += f" | {self.selected_company}"
                self.selection_label.text = selection_text

    def load_settings(self):
        """Load app settings"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r") as f:
                    settings = json.load(f)
                    self.upload_url = settings.get("upload_url", self.upload_url)
                    self.company_db_url = settings.get("company_db_url", self.company_db_url)
                    self.delivery_url = settings.get("delivery_url", self.delivery_url)
                    self.selected_route = settings.get("selected_route", "")
                    self.selected_company = settings.get("selected_company", "")
                    self.driver_id = settings.get("driver_id", "")
                    self.app_mode = settings.get("app_mode", "delivery")  # Default to delivery
                    self.theme_preference = settings.get("theme_preference", self.theme_preference)
                    # Apply theme after loading preference
                    self.apply_theme(self.theme_preference)
        except Exception as e:
            print(f"Error loading settings: {e}")

    def save_settings(self):
        """Save app settings"""
        try:
            settings = {
                "upload_url": self.upload_url,
                "company_db_url": self.company_db_url,
                "delivery_url": self.delivery_url,
                "selected_route": self.selected_route,
                "selected_company": self.selected_company,
                "driver_id": self.driver_id,
                "app_mode": self.app_mode,
                "theme_preference": self.theme_preference,
            }
            with open(self.settings_file, "w") as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def detect_system_theme(self):
        """Best-effort detect system theme. Returns 'light' or 'dark'."""
        try:
            if ANDROID and ANDROID_IMPORTS_WORKING:
                from jnius import autoclass
                UiModeManager = autoclass('android.app.UiModeManager')
                Context = autoclass('android.content.Context')
                activity = autoclass('org.kivy.android.PythonActivity').mActivity
                ui_mode_manager = activity.getSystemService(Context.UI_MODE_SERVICE)
                if ui_mode_manager.getNightMode() in [UiModeManager.MODE_NIGHT_YES]:
                    return "dark"
        except Exception as e:
            print(f"System theme detect failed: {e}")
        # Fallback
        return "light"

    def apply_theme(self, preference: str):
        """Apply theme colors to entire widget tree based on preference."""
        self.theme_preference = preference
        effective = preference
        if preference == "system":
            effective = self.detect_system_theme()
        if effective == "dark":
            self.bg_color = "black"
            self.text_color = "white"
            self.accent_color = self.brand_red  # red as accent in dark
            self.button_text_color = "white"
        else:
            self.bg_color = "white"
            self.text_color = "black"
            self.accent_color = self.brand_blue  # blue as accent in light
            self.button_text_color = "white"

        def _themeize(widget):
            try:
                # Backgrounds for containers
                if isinstance(widget, toga.Box):
                    widget.style.background_color = self.bg_color
                if isinstance(widget, toga.ScrollContainer):
                    widget.style.background_color = self.bg_color
                # Text colors
                if isinstance(widget, toga.Label):
                    widget.style.color = self.text_color
                if isinstance(widget, toga.TextInput):
                    # Text color; some platforms ignore background on inputs
                    widget.style.color = self.text_color
                    # Make inputs readable against bg
                    # widget.style.background_color may not be supported across platforms
                if isinstance(widget, (toga.Button,)):
                    widget.style.background_color = self.accent_color
                    widget.style.color = self.button_text_color
                if isinstance(widget, (toga.Switch, toga.Selection)):
                    # Controls with labels/text
                    widget.style.color = self.text_color
                # Recurse into children if any
                for child in getattr(widget, 'children', []) or []:
                    _themeize(child)
                # ScrollContainer has .content instead of .children
                if hasattr(widget, 'content') and widget.content is not None and widget not in getattr(self, '_visited_theming', set()):
                    _themeize(widget.content)
            except Exception as e:
                print(f"themeize error: {e}")

        try:
            # Apply to existing major screens if they exist
            for box_name in [
                'route_selection_screen', 'company_management_screen', 'settings_screen',
                'pickup_home_screen', 'add_po_screen', 'delivery_home_screen'
            ]:
                box = getattr(self, box_name, None)
                if box is not None:
                    _themeize(box)
            # Also theme the currently visible content
            if getattr(self, 'main_window', None) and getattr(self.main_window, 'content', None):
                _themeize(self.main_window.content)
        except Exception as e:
            print(f"apply_theme error: {e}")

    def show_loading(self, message: str = "Loading..."):
        """Show a blocking loading view by temporarily replacing window content (Toga 0.5.2-safe)."""
        try:
            # If already showing, just update
            if getattr(self, '_loading_view', None) is not None:
                if getattr(self, '_loading_label', None) is not None:
                    self._loading_label.text = message
                return

            # Save current content
            self._saved_content = getattr(self.main_window, 'content', None)

            # Build a simple centered loading view
            outer = toga.Box(style=Pack(direction=COLUMN, padding=20, alignment=CENTER, background_color=self.bg_color))
            inner = toga.Box(style=Pack(direction=COLUMN, padding=20, alignment=CENTER, background_color=self.bg_color))
            spinner = toga.ActivityIndicator(style=Pack(padding_bottom=10))
            spinner.start()
            label = toga.Label(message, style=Pack(color=self.text_color))
            inner.add(spinner)
            inner.add(label)
            outer.add(inner)

            self._loading_view = outer
            self._loading_label = label
            self.main_window.content = self._loading_view
        except Exception as e:
            print(f"show_loading error: {e}")

    def hide_loading(self):
        try:
            # Preferred path: restore content swapped out by show_loading()
            if getattr(self, '_loading_view', None) is not None:
                saved = getattr(self, '_saved_content', None)
                if saved is not None:
                    self.main_window.content = saved
                self._loading_view = None
                self._loading_label = None
                self._saved_content = None
                return

            # Legacy path (older overlay-based loading implementation)
            if getattr(self, 'loading_overlay', None):
                # Remove overlay while keeping original content (first child)
                container = self.main_window.content
                if isinstance(container, toga.Box) and len(container.children) >= 1:
                    # Remove overlay
                    container.children = [c for c in container.children if c is not self.loading_overlay]
                    self.loading_overlay = None
                    self.loading_label = None
                    # If only one child left, set it as content directly
                    if len(container.children) == 1:
                        self.main_window.content = container.children[0]
                else:
                    self.main_window.content = container  # fallback
        except Exception as e:
            print(f"hide_loading error: {e}")

    def show_company_selection(self, widget=None):
        """Show company selection screen - works for both modes"""
        if not self.selected_route:
            self.show_dialog_async("error", "No Route", "Please select a route first")
            return

        main_box = toga.Box(style=Pack(direction=COLUMN, padding=20))
        title = toga.Label("Select Company", style=Pack(font_size=24, padding_bottom=20, text_align=CENTER))
        main_box.add(title)

        add_new_btn = toga.Button("➕ Add New Company", on_press=self.show_add_company_screen,
                                  style=Pack(padding_bottom=20))
        main_box.add(add_new_btn)

        # Get companies from both sources
        all_companies = set()

        # From company database
        if self.selected_route in self.company_database:
            all_companies.update(self.company_database[self.selected_route])

        # From delivery data
        all_companies.update(self.delivery_companies)

        company_list_box = toga.Box(style=Pack(direction=COLUMN, flex=1))
        companies = sorted(list(all_companies))

        if not companies:
            no_companies_label = toga.Label("No companies found for this route.",
                                            style=Pack(padding=20, text_align=CENTER))
            company_list_box.add(no_companies_label)
        else:
            for company in companies:
                # Mark companies with delivery data
                display_text = company
                if company in self.delivery_companies:
                    display_text = f"📦 {company}"

                company_btn = toga.Button(
                    display_text,
                    on_press=lambda w, c=company: self.select_company(c),
                    style=Pack(padding=10, margin=2)
                )
                company_list_box.add(company_btn)

        scroll_container = toga.ScrollContainer(content=company_list_box, style=Pack(flex=1))
        back_btn = toga.Button("Back", on_press=self.show_current_home, style=Pack(padding_top=20))

        main_box.add(scroll_container)
        main_box.add(back_btn)
        self.main_window.content = main_box

    def select_company(self, company):
        """Select a company; enforce that it has at least one frequent blade"""
        # Enforce frequent blade rule
        has_blades = True
        if self.selected_route in self.company_database:
            data = self.company_database[self.selected_route].get(company, {})
            blades = data.get("frequent_blades", [])
            if not blades:
                has_blades = False
        else:
            has_blades = False

        if not has_blades:
            # Prompt user and navigate to management
            self.show_dialog_async(
                "error",
                "No Blades Configured",
                "This company has no frequent blades configured.\nPlease add at least one in Company Database."
            )
            # Navigate to management pre-selected
            self.selected_company = company
            self.save_settings()
            self.main_window.content = self.company_management_screen
            # Preselect in management if possible
            if hasattr(self, 'manage_route_dropdown'):
                self.manage_route_dropdown.value = self.selected_route
                self.on_manage_route_change(self.manage_route_dropdown)
                if hasattr(self, 'manage_company_dropdown'):
                    self.manage_company_dropdown.value = company
                    self.on_manage_company_change(self.manage_company_dropdown)
            return

        self.selected_company = company
        self.save_settings()

        if self.app_mode == "delivery" and company in self.delivery_companies:
            # Find the index of the selected company in delivery data
            try:
                self.current_delivery_index = self.delivery_companies.index(company)
            except ValueError:
                self.current_delivery_index = 0

        self.show_current_home()

    def sync_company_database_on_startup(self):
        """Sync company database on app startup"""

        def sync_task():
            try:
                print("Starting automatic company database sync on startup...")
                success = self.sync_company_database(replace=False)
                if success:
                    print("Company database synced successfully on startup")
                else:
                    print("Company database sync failed on startup")
            except Exception as e:
                print(f"Error during startup sync: {e}")

        thread = threading.Thread(target=sync_task)
        thread.daemon = True
        thread.start()

    def load_company_database(self):
        """Load company database from file"""
        try:
            if os.path.exists(self.company_db_file):
                with open(self.company_db_file, "r") as f:
                    self.company_database = json.load(f)
                self.update_route_company_lists()
                print("Company database loaded")
            else:
                self.company_database = {}
                self.update_route_company_lists()
                print("No company database found, created empty")
        except Exception as e:
            print(f"Error loading company database: {e}")
            self.company_database = {}
            self.update_route_company_lists()

    def save_company_database(self):
        """Save company database to file"""
        try:
            with open(self.company_db_file, "w") as f:
                json.dump(self.company_database, f, indent=2)
            self.update_route_company_lists()
            print("Company database saved")
            return True
        except Exception as e:
            print(f"Error saving company database: {e}")
            return False

    def update_route_company_lists(self):
        """Update available routes and companies from database"""
        self.available_routes = list(self.company_database.keys())
        if self.selected_route and self.selected_route in self.company_database:
            self.company_names = list(self.company_database[self.selected_route].keys())
        else:
            self.company_names = []
        print(f"Updated lists - Routes: {len(self.available_routes)}, Companies: {len(self.company_names)}")
        if self.selected_company and self.selected_company not in self.company_names:
            print(f"Company '{self.selected_company}' no longer exists in route '{self.selected_route}'")
            self.selected_company = ""
            self.save_settings()

    def sync_company_database(self, replace=False):
        """Sync company database with server"""
        try:
            print(f"Syncing company database from {self.company_db_url}")
            response = requests.get(self.company_db_url, timeout=10)
            if response.status_code == 200:
                server_db = response.json()
                print(f"Received company database with {len(server_db)} routes")
                converted_db = {}
                for route, companies in server_db.items():
                    converted_db[route] = {}
                    for company, data in companies.items():
                        descriptions = data.get("descriptions", [])
                        converted_db[route][company] = {"frequent_blades": descriptions}
                if replace:
                    self.company_database = converted_db
                else:
                    for route, companies in converted_db.items():
                        if route not in self.company_database:
                            self.company_database[route] = {}
                        for company, data in companies.items():
                            if company in self.company_database[route]:
                                existing_data = self.company_database[route][company]
                                existing_blades = existing_data.get("frequent_blades", [])
                                new_blades = data.get("frequent_blades", [])
                                merged_blades = list(set(existing_blades + new_blades))
                                existing_data["frequent_blades"] = merged_blades
                            else:
                                self.company_database[route][company] = data
                self.save_company_database()
                self.update_route_company_lists()
                if hasattr(self, 'route_selection'):
                    self.route_selection.items = self.available_routes
                return True
            else:
                print(f"Server returned status: {response.status_code}")
                return False
        except Exception as e:
            print(f"Error syncing company database: {e}")
            import traceback
            traceback.print_exc()
            return False

    def create_mode_selection_screen(self):
        """Create screen to select app mode"""
        main_box = toga.Box(style=Pack(direction=COLUMN, padding=40, alignment=CENTER))

        title = toga.Label(
            "Select Mode",
            style=Pack(text_align=CENTER, font_size=28, padding_bottom=40)
        )
        main_box.add(title)

        # Pickup Mode Button
        pickup_btn = toga.Button(
            "📦 PICKUP MODE",
            on_press=lambda w: self.set_app_mode("pickup"),
            style=Pack(padding=20, font_size=18, width=250, height=80, margin_bottom=20)
        )
        main_box.add(pickup_btn)

        # Delivery Mode Button
        delivery_btn = toga.Button(
            "🚚 DELIVERY MODE",
            on_press=lambda w: self.set_app_mode("delivery"),
            style=Pack(padding=20, font_size=18, width=250, height=80)
        )
        main_box.add(delivery_btn)

        return main_box

    def set_app_mode(self, mode):
        """Set the app mode and show appropriate screen"""
        self.app_mode = mode
        self.save_settings()

        if mode == "pickup":
            if not self.selected_route:
                self.main_window.content = self.route_selection_screen
            else:
                self.main_window.content = self.pickup_home_screen
                self.load_pos()
        else:
            self.main_window.content = self.delivery_route_screen

    def create_delivery_route_screen(self):
        """Create route selection screen for delivery mode"""
        main_box = toga.Box(style=Pack(direction=COLUMN, padding=20))

        title = toga.Label(
            "Delivery Mode - Select Route",
            style=Pack(text_align=CENTER, font_size=24, padding_bottom=20)
        )
        main_box.add(title)

        # Route selection dropdown
        self.delivery_route_selection = toga.Selection(
            items=self.available_routes if self.available_routes else [
                "Mercer", "Punxy", "Middlefield", "Sparty", "Conneautville",
                "Townville", "Holmes County", "Cochranton"
            ],
            style=Pack(padding_bottom=20)
        )
        main_box.add(self.delivery_route_selection)

        # Continue button
        continue_btn = toga.Button(
            "Continue",
            on_press=self.select_delivery_route,
            style=Pack(padding=10)
        )
        main_box.add(continue_btn)

        # Switch to pickup mode button
        switch_mode_btn = toga.Button(
            "Switch to Pickup Mode",
            on_press=lambda w: self.set_app_mode("pickup"),
            style=Pack(padding=10, margin_top=20)
        )
        main_box.add(switch_mode_btn)

        return main_box

    def select_delivery_route(self, widget):
        """Handle route selection in delivery mode"""
        selected = self.delivery_route_selection.value
        if selected and selected != "No routes available":
            self.selected_route = selected
            self.save_settings()
            self.show_delivery_home()

    def show_delivery_home(self, widget=None):
        """Show delivery home screen"""
        if hasattr(self, 'delivery_route_label'):
            self.delivery_route_label.text = f"Route: {self.selected_route}"
        self.main_window.content = self.delivery_home_screen
        self.load_delivery_pos()

    def show_delivery_route_selection(self, widget=None):
        """Show delivery route selection screen"""
        self.main_window.content = self.delivery_route_screen

    def download_delivery_pos(self, widget):
        """Download all POs for the selected route"""
        if not self.selected_route:
            self.show_dialog_async("error", "Error", "Please select a route first")
            return

        async def download_task():
            try:
                await self.main_window.dialog(
                    toga.InfoDialog(
                        title="Downloading",
                        message=f"Downloading POs for route: {self.selected_route}\nPlease wait..."
                    )
                )

                # Call API to get delivery POs
                params = {"route": self.selected_route}
                response = requests.get(self.delivery_api_url, params=params, timeout=30)

                if response.status_code == 200:
                    result = response.json()

                    if not result.get('success', False):
                        error_msg = result.get('error', 'Unknown error')
                        await self.main_window.dialog(
                            toga.ErrorDialog(
                                title="API Error",
                                message=f"Server error: {error_msg}"
                            )
                        )
                        return

                    delivery_data = result.get('data', [])

                    if not delivery_data:
                        await self.main_window.dialog(
                            toga.InfoDialog(
                                title="No POs",
                                message=f"No delivery POs found for route: {self.selected_route}"
                            )
                        )
                        return

                    # Save to local file
                    with open(self.delivery_data_file, "w") as f:
                        json.dump(delivery_data, f, indent=2)

                    # Update the delivery PO list
                    self.load_delivery_pos()

                    await self.main_window.dialog(
                        toga.InfoDialog(
                            title="Download Complete",
                            message=f"Downloaded {len(delivery_data)} delivery POs"
                        )
                    )
                else:
                    await self.main_window.dialog(
                        toga.ErrorDialog(
                            title="Download Error",
                            message=f"Server error: {response.status_code}\n{response.text}"
                        )
                    )

            except Exception as e:
                import traceback
                traceback.print_exc()
                await self.main_window.dialog(
                    toga.ErrorDialog(
                        title="Download Error",
                        message=f"Failed to download: {str(e)}"
                    )
                )

        asyncio.create_task(download_task())

    def check_delivery_folder(self, widget=None):
        """Check and show the current delivery folder location"""
        current_date = datetime.now().strftime("%Y-%m-%d")
        route_date_dir = os.path.join(self.pdf_base_dir, f"{self.selected_route}_{current_date}")

        # Check if directory exists
        if os.path.exists(route_date_dir):
            files = os.listdir(route_date_dir)
            file_list = "\n".join([f"• {f}" for f in files[:10]])  # Show first 10 files
            if len(files) > 10:
                file_list += f"\n• ... and {len(files) - 10} more files"

            message = f"""
    📁 CURRENT DELIVERY FOLDER:

    Location: {route_date_dir}

    Files in folder:
    {file_list}

    To access:
    1. Open FILE MANAGER
    2. Navigate to: download/PickUpForms/
    3. Open folder: {self.selected_route}_{current_date}/
            """
        else:
            message = f"""
    📁 DELIVERY FOLDER NOT FOUND

    Expected location: {route_date_dir}

    To create delivery files:
    1. Tap 'Download All POs for Route'
    2. Or select POs and tap 'Print Selected'
            """

        self.show_dialog_async("info", "Delivery Folder", message)

    def _create_delivery_pdf_content(self, company, pos, current_date):
        """Create content for delivery PDF"""
        content = []
        content.append("=" * 50)
        content.append(f"DELIVERY RECEIPT - {company}")
        content.append("=" * 50)
        content.append(f"Route: {self.selected_route}")
        content.append(f"Date: {current_date}")
        content.append(f"Driver ID: {self.driver_id}")
        content.append("")
        content.append(f"Total POs: {len(pos)}")
        content.append("-" * 50)

        for i, po in enumerate(pos, 1):
            content.append(f"\n{i}. PO #{po.get('id', 'N/A')}")
            content.append(f"   Description: {po.get('description', 'N/A')}")
            content.append(f"   Quantity: {po.get('quantity', 'N/A')}")

            if po.get('pickup_date'):
                content.append(f"   Pickup Date: {po.get('pickup_date')}")

            if po.get('notes'):
                content.append(f"   Notes: {po.get('notes')}")

            content.append("   " + "-" * 40)
            content.append("   Received By: _________________")
            content.append("   Signature: ___________________")
            content.append("   Date: _______________________")
            content.append("")

        content.append("=" * 50)
        content.append("Driver Notes: __________________________________")
        content.append("")
        content.append("_______________________________________________")
        content.append("")
        content.append("Company Representative Signature: ______________")
        content.append("")
        content.append("=" * 50)

        return "\n".join(content)

    def load_delivery_pos(self, widget=None):
        """Load and display delivery POs"""
        if self.delivery_po_list_box is None:
            return

        self.delivery_po_list_box.clear()
        self.delivery_checkboxes = []

        try:
            if os.path.exists(self.delivery_data_file):
                with open(self.delivery_data_file, "r") as f:
                    delivery_data = json.load(f)
            else:
                delivery_data = []
        except Exception as e:
            print(f"Error loading delivery POs: {e}")
            delivery_data = []

        if not delivery_data or not isinstance(delivery_data, list):
            no_data_label = toga.Label(
                "No delivery POs found.\nTap 'Download All POs for Route' to fetch delivery data.",
                style=Pack(padding=20, text_align=CENTER, font_size=14)
            )
            self.delivery_po_list_box.add(no_data_label)
            return

        # Group POs by company
        companies = {}
        for i, po in enumerate(delivery_data):
            company = po.get('company', 'Unknown')
            if company not in companies:
                companies[company] = []
            companies[company].append((i, po))

        # Display POs grouped by company
        for company, po_list in companies.items():
            # Company header
            company_header = toga.Label(
                f"📦 {company}",
                style=Pack(font_size=16, font_weight="bold", padding_top=15, padding_bottom=8)
            )
            self.delivery_po_list_box.add(company_header)

            # List POs for this company
            for index, po in po_list:
                row_box = toga.Box(style=Pack(direction=ROW, padding=8, margin_left=15, margin_right=10))

                # Checkbox for selection
                checkbox = toga.Switch('', style=Pack(width=50, padding_right=10))
                self.delivery_checkboxes.append((checkbox, index))

                # PO info
                po_id = po.get('id', 'N/A')
                description = po.get('description', 'No description')
                quantity = po.get('quantity', 'N/A')

                po_text = f"PO #{po_id}: {description} - Qty: {quantity}"
                if len(po_text) > 60:
                    po_text = po_text[:57] + "..."

                label = toga.Label(
                    po_text,
                    style=Pack(flex=1, font_size=13)
                )

                row_box.add(checkbox)
                row_box.add(label)
                self.delivery_po_list_box.add(row_box)

                # Add separator line
                separator = toga.Box(
                    style=Pack(height=1, background_color="#e0e0e0", margin_left=15, margin_right=10)
                )
                self.delivery_po_list_box.add(separator)

    def create_route_selection_screen(self):
        """Create route selection screen"""
        main_box = toga.Box(style=Pack(direction=COLUMN, padding=20))

        title = toga.Label(
            "Select Route",
            style=Pack(text_align=CENTER, font_size=24, padding_bottom=20)
        )
        main_box.add(title)

        # Route selection dropdown
        self.route_selection = toga.Selection(
            items=self.available_routes if self.available_routes else ["Mercer",
                                                                       "Punxy",
                                                                       "Middlefield",
                                                                       "Sparty",
                                                                       "Conneautville",
                                                                       "Townville",
                                                                       "Holmes County",
                                                                       "Cochranton"],
            style=Pack(padding_bottom=20)
        )
        main_box.add(self.route_selection)

        # Continue button
        continue_btn = toga.Button(
            "Continue",
            on_press=self.select_route,
            style=Pack(padding=10)
        )
        main_box.add(continue_btn)

        return main_box

    def select_route(self, widget):
        """Handle route selection"""
        selected = self.route_selection.value
        if selected and selected != "No routes available":
            self.selected_route = selected
            self.save_settings()
            if hasattr(self, 'selection_label'):
                selection_text = f"{self.selected_route}"
                if self.selected_company:
                    selection_text += f" | {self.selected_company}"
                self.selection_label.text = selection_text
                route_label = f"Route: {self.selected_route if self.selected_route else 'Not Selected'}"

                self.route_label.text = route_label
            self.update_route_company_lists()
            self.show_home()

    def create_home_screen(self):
        """Create main home screen with PO list"""
        main_box = toga.Box(style=Pack(direction=COLUMN, padding=10))

        # Header with route and company
        header_box = toga.Box(style=Pack(direction=ROW, padding_bottom=10))

        # Display current selections
        selection_text = f"{self.selected_route}"
        if self.selected_company:
            selection_text += f" | {self.selected_company}"

        self.selection_label = toga.Label(
            selection_text,
            style=Pack(flex=1, font_size=16)
        )
        header_box.add(self.selection_label)

        # Change buttons
        button_box = toga.Box(style=Pack(direction=ROW))
        change_route_btn = toga.Button(
            "Change Route",
            on_press=self.show_route_selection,
            style=Pack(padding_left=5, width=120, height=60)
        )
        change_company_btn = toga.Button(
            "Change Company",
            on_press=self.show_company_selection,
            style=Pack(padding_left=5, width=120, height=60)
        )
        button_box.add(change_route_btn)
        button_box.add(change_company_btn)

        # PO List
        self.po_list_box = toga.Box(style=Pack(direction=COLUMN, flex=1))
        po_scroll = toga.ScrollContainer(
            content=self.po_list_box,
            style=Pack(flex=1)
        )

        # Action buttons
        action_box = toga.Box(style=Pack(direction=COLUMN, padding_top=10))

        row1 = toga.Box(style=Pack(direction=ROW, padding_bottom=5))
        row2 = toga.Box(style=Pack(direction=ROW))

        add_btn = toga.Button("Add New", on_press=self.show_add_po, style=Pack(flex=1, padding=5))
        upload_btn = toga.Button("Upload", on_press=self.upload_selected, style=Pack(flex=1, padding=5))
        delete_btn = toga.Button("Delete", on_press=self.delete_selected, style=Pack(flex=1, padding=5))

        update_btn = toga.Button("Update", on_press=self.update_selected, style=Pack(flex=1, padding=5))
        settings_btn = toga.Button("Settings", on_press=self.show_settings, style=Pack(flex=1, padding=5))
        refresh_btn = toga.Button("Refresh", on_press=self.load_pos, style=Pack(flex=1, padding=5))

        row1.add(add_btn)
        row1.add(upload_btn)
        row1.add(delete_btn)

        row2.add(update_btn)
        row2.add(settings_btn)
        row2.add(refresh_btn)

        action_box.add(row1)
        action_box.add(row2)

        # Compose layout
        main_box.add(header_box)
        main_box.add(button_box)
        main_box.add(po_scroll)
        main_box.add(action_box)

        return main_box

    def show_add_company_screen(self, widget):
        """Show add company screen"""
        main_box = toga.Box(style=Pack(direction=COLUMN, padding=20))

        title = toga.Label(
            "Add New Company",
            style=Pack(font_size=24, padding_bottom=20, text_align=CENTER)
        )
        main_box.add(title)

        # Company name input
        company_label = toga.Label("Company Name:", style=Pack(padding_bottom=5))
        self.new_company_input = toga.TextInput(
            placeholder="Enter company name",
            style=Pack(padding_bottom=10)
        )
        main_box.add(company_label)
        main_box.add(self.new_company_input)

        # Buttons
        button_box = toga.Box(style=Pack(direction=ROW, padding_top=10))
        save_btn = toga.Button(
            "Save",
            on_press=self.save_new_company,
            style=Pack(flex=1, padding_right=5)
        )
        cancel_btn = toga.Button(
            "Cancel",
            on_press=self.show_company_selection,
            style=Pack(flex=1, padding_left=5)
        )
        button_box.add(save_btn)
        button_box.add(cancel_btn)
        main_box.add(button_box)

        # Set the main window content
        self.main_window.content = main_box

    def save_new_company(self, widget):
        """Save new company and return to company selection"""
        company_name = self.new_company_input.value.strip() if self.new_company_input else ""

        if not company_name:
            self.show_dialog_async("error", "Error", "Please enter a company name")
            return

        if self.selected_route not in self.company_database:
            self.company_database[self.selected_route] = {}

        if company_name in self.company_database[self.selected_route]:
            self.show_dialog_async("error", "Error", "Company already exists")
            return

        # Add the new company
        self.company_database[self.selected_route][company_name] = {"frequent_blades": []}
        self.save_company_database()
        self.update_route_company_lists()

        # Select the new company
        self.selected_company = company_name
        self.save_settings()

        # Show success message and return to home
        self.show_home()
        self.show_dialog_async("info", "Success", f"Company '{company_name}' added")

    def update_frequent_blades_list(self):
        self.frequent_blades = []
        if (self.selected_route in self.company_database and
                self.selected_company in self.company_database[self.selected_route]):
            self.frequent_blades = self.company_database[self.selected_route][self.selected_company].get(
                "frequent_blades", [])

    def create_add_po_screen(self):
        """Create the add/update PO screen with simplified 2-step flow"""
        main_box = toga.Box(style=Pack(direction=COLUMN, padding=10))

        # Header with current selections
        header_box = toga.Box(style=Pack(direction=COLUMN, padding_bottom=10))
        self.selected_info_label = toga.Label(
            f"{self.selected_route} | {self.selected_company}",
            style=Pack(font_size=16, padding_bottom=10)
        )
        header_box.add(self.selected_info_label)

        # Step 1: Description selection
        self.step1_box = toga.Box(style=Pack(direction=COLUMN))

        step1_label = toga.Label(
            "Select Frequent Blade or Enter Description:",
            style=Pack(font_size=16, padding_bottom=10)
        )
        self.step1_box.add(step1_label)

        # Don't update here - let update_add_po_screen handle it
        # self.update_frequent_blades_list()

        # Frequent blades dropdown (initialize empty, will be populated)
        self.blade_dropdown = toga.Selection(
            items=[],  # Start empty
            style=Pack(padding_bottom=10)
        )
        self.step1_box.add(self.blade_dropdown)

        # Custom description input (initially hidden)
        self.custom_desc_container = toga.Box(style=Pack(direction=COLUMN))
        custom_desc_label = toga.Label("Custom Description:", style=Pack(padding_bottom=5))
        self.custom_desc_input = toga.TextInput(
            placeholder="Enter description",
            style=Pack(padding_bottom=10)
        )
        self.custom_desc_container.add(custom_desc_label)
        self.custom_desc_container.add(self.custom_desc_input)
        self.step1_box.add(self.custom_desc_container)

        # Note: Removed explicit 'Next' button to simplify flow; both sections visible at once

        # Step 2: Quantity and date (now always visible)
        self.step2_box = toga.Box(style=Pack(direction=COLUMN))

        step2_label = toga.Label(
            "Enter Quantity Received:",
            style=Pack(font_size=16, padding_bottom=10)
        )
        self.step2_box.add(step2_label)

        # Quantity input
        self.qty_input = toga.TextInput(
            placeholder="Enter quantity",
            style=Pack(padding_bottom=10)
        )
        self.step2_box.add(self.qty_input)

        # Auto-filled date (read-only)
        current_date = datetime.now().strftime("%m/%d/%Y")
        self.date_label = toga.Label(
            f"Pickup Date: {current_date}",
            style=Pack(padding_bottom=10, font_size=14)
        )
        self.step2_box.add(self.date_label)

        # Action buttons for saving
        step2_btn_box = toga.Box(style=Pack(direction=ROW, padding_top=10))

        self.save_btn = toga.Button(
            "Save PO",
            on_press=self.save_po_form,
            style=Pack(flex=1)
        )

        step2_btn_box.add(self.save_btn)
        self.step2_box.add(step2_btn_box)

        # Cancel button (always visible)
        cancel_btn = toga.Button(
            "Cancel",
            on_press=self.show_home,
            style=Pack(padding_top=20)
        )

        # Assemble screen
        main_box.add(header_box)
        main_box.add(self.step1_box)
        main_box.add(self.step2_box)
        main_box.add(cancel_btn)

        # Wire up blade dropdown change event
        self.blade_dropdown.on_change = self.on_blade_selection_change

        return main_box

    def on_blade_selection_change(self, widget):
        """Handle blade selection change"""
        selected = widget.value
        if selected == "--- Enter Custom Description ---":
            self.custom_desc_container.visible = True
        else:
            self.custom_desc_container.visible = False
            self.custom_desc_input.value = ""

    def go_to_step2(self, widget):
        """Move from step 1 to step 2"""
        # Validate step 1
        selected_blade = self.blade_dropdown.value
        custom_desc = self.custom_desc_input.value.strip()

        if not selected_blade:
            self.show_dialog_async("error", "Missing Information", "Please select or enter a description")
            return

        if selected_blade == "--- Enter Custom Description ---" and not custom_desc:
            self.show_dialog_async("error", "Missing Information", "Please enter a description")
            return

        # Hide step 1, show step 2
        self.step1_box.visible = False
        self.step2_box.visible = True

        # Focus quantity field
        self.qty_input.focus()

    def go_to_step1(self, widget):
        """Move from step 2 back to step 1"""
        self.step2_box.visible = False
        self.step1_box.visible = True

    def save_po_form(self, widget):
        """Save PO form data"""
        try:
            # Get data from form
            selected_blade = self.blade_dropdown.value
            custom_desc = self.custom_desc_input.value.strip()
            quantity = self.qty_input.value.strip()
            current_date = datetime.now().strftime("%m/%d/%Y")

            # Determine description
            if selected_blade == "--- Enter Custom Description ---":
                description = custom_desc
            else:
                description = selected_blade

            # Validation
            if not description:
                self.show_dialog_async("error", "Missing Information", "Please enter a description")
                return

            if not quantity:
                self.show_dialog_async("error", "Missing Information", "Please enter quantity")
                return

            if not self.selected_company:
                self.show_dialog_async("error", "Missing Company", "Please select a company first")
                return

            # Enforce frequent blade association for selected company
            blades_ok = False
            if self.selected_route in self.company_database:
                company_data = self.company_database[self.selected_route].get(self.selected_company, {})
                blades = company_data.get("frequent_blades", [])
                blades_ok = len(blades) > 0
            if not blades_ok:
                self.show_dialog_async(
                    "error",
                    "No Blades Configured",
                    "This company has no frequent blades configured.\nPlease add at least one in Company Database."
                )
                return

            # Create PO object with new order
            po_data = {
                "uploaded": "no",
                "description": description,
                "company": self.selected_company,
                "route": self.selected_route,
                "quantity": quantity,
                "pickup_date": current_date,
                "driver_id": self.driver_id,
                "created_at": datetime.now().isoformat()
            }

            # Load existing data
            if os.path.exists(self.data_file):
                with open(self.data_file, "r") as f:
                    data = json.load(f)
            else:
                data = []

            # Update or add
            if self.editing_index is not None and 0 <= self.editing_index < len(data):
                data[self.editing_index] = po_data
            else:
                data.append(po_data)

            # Save
            with open(self.data_file, "w") as f:
                json.dump(data, f, indent=2)

            # Clear form and return to home
            self.reset_form()
            self.show_home()

            # Show success message
            self.show_dialog_async("info", "Success", "PO saved successfully!")

        except Exception as e:
            self.show_dialog_async("error", "Error", f"Failed to save: {str(e)}")

    def load_pos(self, widget=None):
        """Load and display POs with new format"""
        self.po_list_box.clear()
        self.checkboxes = []  # Store checkbox references

        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, "r") as f:
                    pos = json.load(f)
            else:
                pos = []
        except Exception as e:
            print(f"Error loading POs: {e}")
            pos = []

        for i, po in enumerate(pos):
            # Create row with new format: uploaded, description, company, route
            uploaded = "yes" if po.get("uploaded") == True else "no"
            description = po.get("description", "N/A")
            company = po.get("company", "N/A")
            route = po.get("route", "N/A")

            # Format display text without descriptors
            display_text = f"{uploaded}  {description}  {company}  {route}"

            row_box = toga.Box(style=Pack(direction=ROW, padding=5))

            # Checkbox for selection
            checkbox = toga.Switch('', style=Pack(width=50))
            self.checkboxes.append(checkbox)

            # PO label with simplified display
            label = toga.Label(
                display_text,
                style=Pack(flex=1, font_size=14)
            )

            edit_btn = toga.Button(
                "Edit",
                on_press=lambda w, idx=i: self.edit_po_at_index(idx),
                style=Pack(width=70, padding_left=5, padding_right=5)
            )
            delete_btn = toga.Button(
                "Delete",
                on_press=lambda w, idx=i: self.delete_po_at_index(idx),
                style=Pack(width=80)
            )

            row_box.add(checkbox)
            row_box.add(label)
            row_box.add(edit_btn)
            row_box.add(delete_btn)

            self.po_list_box.add(row_box)

    def reset_form(self):
        """Reset the add/update form"""
        self.editing_index = None

        # Update frequent blades list
        self.update_frequent_blades_list()

        # Update screen if it exists
        if hasattr(self, 'add_po_screen'):
            self.update_add_po_screen()

    def edit_po_at_index(self, index: int):
        """Load a PO at index into the form for editing and navigate to the add/edit screen."""
        try:
            if not os.path.exists(self.data_file):
                self.show_dialog_async("error", "No Data", "No saved pick up forms found.")
                return
            with open(self.data_file, "r") as f:
                data = json.load(f)
            if index < 0 or index >= len(data):
                self.show_dialog_async("error", "Invalid Selection", "That item no longer exists.")
                return
            po = data[index]
            # Set selection context
            self.selected_route = po.get("route", self.selected_route)
            self.selected_company = po.get("company", self.selected_company)
            self.save_settings()

            # Ensure blades list for selected company is up to date
            self.update_frequent_blades_list()

            # Prepare form fields
            desc = po.get("description", "")
            qty = str(po.get("quantity", ""))

            # Navigate/create form if needed
            if not hasattr(self, 'add_po_screen') or self.add_po_screen is None:
                self.add_po_screen = self.create_add_po_screen()
            self.update_add_po_screen()

            # Fill quantity
            if hasattr(self, 'qty_input'):
                self.qty_input.value = qty

            # Choose blade or custom
            if hasattr(self, 'blade_dropdown') and hasattr(self, 'custom_desc_container') and hasattr(self, 'custom_desc_input'):
                items = self.frequent_blades
                if desc in items:
                    # Select known blade
                    try:
                        self.blade_dropdown.value = desc
                        self.custom_desc_container.visible = False
                        self.custom_desc_input.value = ""
                    except Exception:
                        pass
                else:
                    # Use custom description
                    try:
                        # Ensure the custom option exists and is selected
                        custom_label = "--- Enter Custom Description ---"
                        if custom_label not in self.blade_dropdown.items:
                            self.blade_dropdown.items = list(self.blade_dropdown.items) + [custom_label]
                        self.blade_dropdown.value = custom_label
                        self.custom_desc_container.visible = True
                        self.custom_desc_input.value = desc
                    except Exception:
                        pass

            # Set editing index and navigate
            self.editing_index = index
            if hasattr(self, 'selected_info_label'):
                self.selected_info_label.text = f"{self.selected_route} | {self.selected_company}"
            self.main_window.content = self.add_po_screen
        except Exception as e:
            self.show_dialog_async("error", "Error", f"Failed to load item: {str(e)}")

    def delete_po_at_index(self, index: int):
        """Delete a single PO entry and refresh the list."""
        try:
            if not os.path.exists(self.data_file):
                return
            with open(self.data_file, "r") as f:
                data = json.load(f)
            if index < 0 or index >= len(data):
                return
            # Remove the entry
            data.pop(index)
            with open(self.data_file, "w") as f:
                json.dump(data, f, indent=2)
            self.load_pos()
            self.show_dialog_async("info", "Deleted", "The pick up form was deleted.")
        except Exception as e:
            self.show_dialog_async("error", "Error", f"Failed to delete: {str(e)}")

    def sync_company_db_ui(self, widget):
        """Sync company database from UI with deletion option"""

        async def sync_and_show():
            # Ask user if they want to delete existing data
            result = await self.main_window.dialog(
                toga.ConfirmDialog(
                    title="Sync Options",
                    message="How do you want to sync?\n\n"
                            "• Merge: Keep existing data and add new from server\n"
                            "• Replace: Delete all local data and replace with server data"
                )
            )

            if result is None:  # User cancelled
                return

            # Run the sync with the chosen option
            if result:  # User clicked "OK" - this means Replace
                success = self.sync_company_database(replace=True)
                message = "Company database replaced with server data"
            else:  # User clicked "Cancel" - this means Merge
                success = self.sync_company_database(replace=False)
                message = "Company database merged with server data"

            if success:
                await self.main_window.dialog(
                    toga.InfoDialog(
                        title="Success",
                        message=f"{message} successfully"
                    )
                )
            else:
                await self.main_window.dialog(
                    toga.ErrorDialog(
                        title="Error",
                        message="Failed to sync company database"
                    )
                )

        asyncio.create_task(sync_and_show())

    def on_manage_route_change(self, widget):
        """Handle route change in company management screen"""
        selected_route = widget.value
        if selected_route:
            # Reset inputs
            self.new_company_input.value = ""
            self.new_blade_input.value = ""
            self._editing_blade = None

            # Update placeholder text to show selected route
            self.new_company_input.placeholder = f"New company for {selected_route}"

            # Populate company dropdown
            companies = []
            if selected_route in self.company_database:
                companies = sorted(list(self.company_database[selected_route].keys()))
            if hasattr(self, 'manage_company_dropdown'):
                self.manage_company_dropdown.items = companies or ["<No companies>"]
                self.manage_company_dropdown.value = companies[0] if companies else None

            # Update blades list for first company (if any)
            self.blades_list.clear()
            if companies:
                self.on_manage_company_change(self.manage_company_dropdown)

            print(f"Selected route for management: {selected_route}")

    def on_manage_company_change(self, widget):
        """Handle company change; refresh blades list."""
        route = self.manage_route_dropdown.value or self.selected_route
        company = widget.value
        if route and company and route in self.company_database and company in self.company_database[route]:
            self.update_blades_list(route, company)
        else:
            self.blades_list.clear()

    def create_company_management_screen(self):
        """Create company database management screen"""
        main_box = toga.Box(style=Pack(direction=COLUMN, padding=10))

        title = toga.Label("Manage Company Database", style=Pack(font_size=24, padding_bottom=10))

        # Route management
        route_label = toga.Label("Add/Remove Route:", style=Pack(padding_bottom=5))

        # Input with larger size
        self.new_route_input = toga.TextInput(
            placeholder="New route name",
            style=Pack(flex=1, padding=(6, 8), height=44, font_size=16, padding_bottom=6)
        )
        # Buttons under the input
        route_buttons = toga.Box(style=Pack(direction=ROW, padding_bottom=10))
        add_route_btn = toga.Button(
            "Add Route",
            on_press=self.add_route,
            style=Pack(flex=1, height=44, padding_right=5)
        )
        rename_route_btn = toga.Button(
            "Rename Route",
            on_press=self.rename_route,
            style=Pack(flex=1, height=44, padding_right=5)
        )
        delete_route_btn = toga.Button(
            "Delete Route",
            on_press=self.delete_route,
            style=Pack(flex=1, height=44)
        )
        route_buttons.add(add_route_btn)
        route_buttons.add(rename_route_btn)
        route_buttons.add(delete_route_btn)

        # Route selector for company management
        self.manage_route_dropdown = toga.Selection(
            items=self.available_routes,
            on_change=self.on_manage_route_change,
            style=Pack(padding_bottom=10, height=44, font_size=16)
        )

        # Company selection & management
        company_label = toga.Label("Companies:", style=Pack(padding_bottom=5))

        # Company selector for selected route
        self.manage_company_dropdown = toga.Selection(
            items=[],
            on_change=self.on_manage_company_change,
            style=Pack(padding_bottom=10, height=44, font_size=16)
        )

        # Larger input stacked with full-width buttons below
        self.new_company_input = toga.TextInput(
            placeholder="New company name",
            style=Pack(flex=1, padding=(6, 8), height=44, font_size=16, padding_bottom=6)
        )
        company_buttons = toga.Box(style=Pack(direction=ROW, padding_bottom=10))
        add_company_btn = toga.Button(
            "Add",
            on_press=self.add_company,
            style=Pack(flex=1, height=44, padding_right=5)
        )
        rename_company_btn = toga.Button(
            "Rename",
            on_press=self.rename_company,
            style=Pack(flex=1, height=44, padding_right=5)
        )
        delete_company_btn = toga.Button(
            "Delete",
            on_press=self.delete_company,
            style=Pack(flex=1, height=44)
        )
        company_buttons.add(add_company_btn)
        company_buttons.add(rename_company_btn)
        company_buttons.add(delete_company_btn)

        # Frequent blades management for selected company
        blade_label = toga.Label("Add/Remove Frequent Blades:", style=Pack(padding_bottom=5))

        # Larger input stacked with button below
        self.new_blade_input = toga.TextInput(
            placeholder="New blade description",
            style=Pack(flex=1, padding=(6, 8), height=44, font_size=16, padding_bottom=6)
        )
        blade_buttons = toga.Box(style=Pack(direction=ROW, padding_bottom=10))
        add_blade_btn = toga.Button(
            "Add Blade",
            on_press=self.add_frequent_blade,
            style=Pack(flex=1, height=44)
        )
        blade_buttons.add(add_blade_btn)

        # Current blades list
        self.blades_list = toga.Box(style=Pack(direction=COLUMN, padding_bottom=10))

        # Action buttons
        button_box = toga.Box(style=Pack(direction=ROW, padding_top=10))

        save_btn = toga.Button(
            "Save Changes",
            on_press=self.save_company_changes,
            style=Pack(flex=1, padding_right=5)
        )

        back_btn = toga.Button(
            "Back",
            on_press=self.show_settings,
            style=Pack(flex=1, padding_left=5)
        )

        button_box.add(save_btn)
        button_box.add(back_btn)

        main_box.add(title)
        main_box.add(route_label)
        main_box.add(self.new_route_input)
        main_box.add(route_buttons)
        main_box.add(self.manage_route_dropdown)
        main_box.add(company_label)
        main_box.add(self.manage_company_dropdown)
        main_box.add(self.new_company_input)
        main_box.add(company_buttons)
        main_box.add(blade_label)
        main_box.add(self.new_blade_input)
        main_box.add(blade_buttons)
        main_box.add(self.blades_list)
        main_box.add(button_box)

        return main_box

    def add_route(self, widget):
        """Add new route to database"""
        new_route = self.new_route_input.value.strip()
        if new_route and new_route not in self.company_database:
            self.company_database[new_route] = {}
            self.new_route_input.value = ""
            self.update_route_company_lists()

            # Update dropdowns
            self.manage_route_dropdown.items = self.available_routes
            self.show_dialog_async("info", "Success", f"Route '{new_route}' added")

    def rename_route(self, widget):
        """Rename selected route to the text in new_route_input"""
        old_route = self.manage_route_dropdown.value
        new_name = self.new_route_input.value.strip()
        if not old_route:
            self.show_dialog_async("error", "No Route Selected", "Select a route to rename")
            return
        if not new_name:
            self.show_dialog_async("error", "Missing Name", "Enter a new route name")
            return
        if new_name in self.company_database:
            self.show_dialog_async("error", "Exists", "A route with that name already exists")
            return
        self.company_database[new_name] = self.company_database.pop(old_route)
        # Update selected route references
        if self.selected_route == old_route:
            self.selected_route = new_name
            self.save_settings()
        self.update_route_company_lists()
        self.manage_route_dropdown.items = self.available_routes
        self.manage_route_dropdown.value = new_name
        self.show_dialog_async("info", "Renamed", f"Route '{old_route}' renamed to '{new_name}'")

    def delete_route(self, widget):
        """Delete selected route"""
        route = self.manage_route_dropdown.value
        if not route:
            self.show_dialog_async("error", "No Route Selected", "Select a route to delete")
            return
        try:
            del self.company_database[route]
            if self.selected_route == route:
                self.selected_route = ""
                self.selected_company = ""
                self.save_settings()
            self.update_route_company_lists()
            self.manage_route_dropdown.items = self.available_routes
            self.manage_company_dropdown.items = []
            self.blades_list.clear()
            self.show_dialog_async("info", "Deleted", f"Route '{route}' deleted")
        except KeyError:
            pass

    def add_company(self, widget):
        """Add new company to current route"""
        selected_route = self.manage_route_dropdown.value or self.selected_route
        new_company = self.new_company_input.value.strip()

        if selected_route and new_company:
            if selected_route not in self.company_database:
                self.company_database[selected_route] = {}

            if new_company not in self.company_database[selected_route]:
                self.company_database[selected_route][new_company] = {"frequent_blades": []}
                self.new_company_input.value = ""
                self.update_route_company_lists()
                # Refresh company dropdown
                companies = sorted(list(self.company_database[selected_route].keys()))
                self.manage_company_dropdown.items = companies
                self.manage_company_dropdown.value = new_company
                self.show_dialog_async("info", "Success", f"Company '{new_company}' added")

    def rename_company(self, widget):
        """Rename selected company to text in new_company_input"""
        route = self.manage_route_dropdown.value or self.selected_route
        old_company = None
        if hasattr(self, 'manage_company_dropdown'):
            old_company = self.manage_company_dropdown.value
        new_name = self.new_company_input.value.strip()
        if not route:
            self.show_dialog_async("error", "No Route", "Select a route first")
            return
        if not old_company:
            self.show_dialog_async("error", "No Company", "Select a company to rename")
            return
        if not new_name:
            self.show_dialog_async("error", "Missing Name", "Enter a new company name")
            return
        if new_name in self.company_database.get(route, {}):
            self.show_dialog_async("error", "Exists", "A company with that name already exists on this route")
            return
        self.company_database[route][new_name] = self.company_database[route].pop(old_company)
        if self.selected_company == old_company and self.selected_route == route:
            self.selected_company = new_name
            self.save_settings()
        self.update_route_company_lists()
        companies = sorted(list(self.company_database[route].keys()))
        self.manage_company_dropdown.items = companies
        self.manage_company_dropdown.value = new_name
        self.update_blades_list(route, new_name)
        self.show_dialog_async("info", "Renamed", f"Company '{old_company}' renamed to '{new_name}'")

    def delete_company(self, widget):
        """Delete selected company from selected route"""
        route = self.manage_route_dropdown.value or self.selected_route
        company = None
        if hasattr(self, 'manage_company_dropdown'):
            company = self.manage_company_dropdown.value
        if not route or not company:
            self.show_dialog_async("error", "Not Selected", "Select a route and company to delete")
            return
        try:
            del self.company_database[route][company]
            if self.selected_route == route and self.selected_company == company:
                self.selected_company = ""
                self.save_settings()
            self.update_route_company_lists()
            companies = sorted(list(self.company_database.get(route, {}).keys()))
            self.manage_company_dropdown.items = companies
            self.manage_company_dropdown.value = companies[0] if companies else None
            self.blades_list.clear()
            self.show_dialog_async("info", "Deleted", f"Company '{company}' deleted")
        except KeyError:
            pass

    def start_edit_blade(self, route, company, blade):
        """Start editing a blade by loading text into input."""
        self._editing_blade = (route, company, blade)
        self.new_blade_input.value = blade
        self.new_blade_input.placeholder = f"Edit blade for {company}"

    def add_frequent_blade(self, widget):
        """Add or edit frequent blade to selected company"""
        selected_route = self.manage_route_dropdown.value or self.selected_route
        selected_company = None
        if hasattr(self, 'manage_company_dropdown') and self.manage_company_dropdown.value:
            selected_company = self.manage_company_dropdown.value
        if not selected_company:
            selected_company = self.new_company_input.value.strip()
        new_blade = self.new_blade_input.value.strip()

        if selected_route and selected_company and new_blade:
            if (selected_route in self.company_database and
                    selected_company in self.company_database[selected_route]):

                company_data = self.company_database[selected_route][selected_company]
                if "frequent_blades" not in company_data:
                    company_data["frequent_blades"] = []

                # If in edit mode
                if getattr(self, '_editing_blade', None):
                    r, c, old_blade = self._editing_blade
                    if r == selected_route and c == selected_company:
                        try:
                            idx = company_data["frequent_blades"].index(old_blade)
                            company_data["frequent_blades"][idx] = new_blade
                        except ValueError:
                            if new_blade not in company_data["frequent_blades"]:
                                company_data["frequent_blades"].append(new_blade)
                    self._editing_blade = None
                else:
                    if new_blade not in company_data["frequent_blades"]:
                        company_data["frequent_blades"].append(new_blade)
                self.new_blade_input.value = ""

                # Update blades list display
                self.update_blades_list(selected_route, selected_company)

    def save_company_changes(self, widget):
        """Save company database changes with validation that each company has at least 1 blade"""
        # Validate: every company must have at least one frequent blade
        for route, companies in self.company_database.items():
            for company, data in companies.items():
                blades = data.get("frequent_blades", [])
                if not blades:
                    self.show_dialog_async(
                        "error",
                        "Missing Blades",
                        f"Company '{company}' on route '{route}' has no frequent blades.\nAdd at least one before saving."
                    )
                    return
        if self.save_company_database():
            self.show_dialog_async("info", "Success", "Company database saved")
        else:
            self.show_dialog_async("error", "Error", "Failed to save company database")

    def update_blades_list(self, route, company):
        """Update the blades list display"""
        self.blades_list.clear()

        if route in self.company_database and company in self.company_database[route]:
            blades = self.company_database[route][company].get("frequent_blades", [])

            for blade in blades:
                blade_box = toga.Box(style=Pack(direction=ROW, padding=2))
                blade_label = toga.Label(blade, style=Pack(flex=1))
                edit_btn = toga.Button(
                    "Edit",
                    on_press=lambda w, b=blade: self.start_edit_blade(route, company, b),
                    style=Pack(width=100, height=44, padding_right=5)
                )
                remove_btn = toga.Button(
                    "Remove",
                    on_press=lambda w, b=blade: self.remove_blade(route, company, b),
                    style=Pack(width=100, height=44)
                )
                blade_box.add(blade_label)
                blade_box.add(edit_btn)
                blade_box.add(remove_btn)
                self.blades_list.add(blade_box)

    def remove_blade(self, route, company, blade):
        """Remove a frequent blade"""
        if (route in self.company_database and
                company in self.company_database[route]):

            company_data = self.company_database[route][company]
            if blade in company_data.get("frequent_blades", []):
                company_data["frequent_blades"].remove(blade)
                self.update_blades_list(route, company)

    def show_dialog_async(self, dialog_type, title, message):
        """Helper to show dialogs"""

        async def show():
            if dialog_type == "info":
                await self.main_window.dialog(
                    toga.InfoDialog(title=title, message=message)
                )
            elif dialog_type == "error":
                await self.main_window.dialog(
                    toga.ErrorDialog(title=title, message=message)
                )

        asyncio.create_task(show())

    # Navigation methods
    def show_home(self, widget=None):
        """Show home screen - modified to respect app mode"""
        if self.app_mode == "delivery":
            self.show_delivery_home()
        else:
            self.main_window.content = self.pickup_home_screen
            self.load_pos()

            # Update selection label
            if hasattr(self, 'selection_label'):
                selection_text = f"{self.selected_route}"
                if self.selected_company:
                    selection_text += f" | {self.selected_company}"
                self.selection_label.text = selection_text

    def show_add_po(self, widget):
        """Show add PO screen"""
        if not self.selected_company:
            # No company selected, show company selection first
            self.show_company_selection()
            return

        self.reset_form()

        # Update the blade dropdown items for current company
        self.update_frequent_blades_list()

        # Create or update the add PO screen
        if not hasattr(self, 'add_po_screen') or self.add_po_screen is None:
            self.add_po_screen = self.create_add_po_screen()
        else:
            # Update existing screen components
            self.update_add_po_screen()

        if hasattr(self, 'selected_info_label'):
            self.selected_info_label.text = f"{self.selected_route} | {self.selected_company}"

        self.main_window.content = self.add_po_screen

    def update_add_po_screen(self):
        """Update the add PO screen with current data"""
        if hasattr(self, 'selected_info_label'):
            self.selected_info_label.text = f"{self.selected_route} | {self.selected_company}"

        # Update blade dropdown items
        if hasattr(self, 'blade_dropdown'):
            items = self.frequent_blades + ["--- Enter Custom Description ---"]
            self.blade_dropdown.items = items

            # Try to set to first item if available
            if items and len(items) > 0:
                try:
                    self.blade_dropdown.value = items[0]
                except:
                    pass

        # Reset visibility
        if hasattr(self, 'custom_desc_container'):
            self.custom_desc_container.visible = False

        # Ensure both sections are visible in simplified flow
        if hasattr(self, 'step1_box'):
            self.step1_box.visible = True
        if hasattr(self, 'step2_box'):
            self.step2_box.visible = True

        # Update date
        if hasattr(self, 'date_label'):
            current_date = datetime.now().strftime("%m/%d/%Y")
            self.date_label.text = f"Pickup Date: {current_date}"

        print(f"Updated PO screen for {self.selected_company} with {len(self.frequent_blades)} blades")

    def show_settings(self, widget):
        self.main_window.content = self.settings_screen

    def show_company_management(self, widget):
        self.main_window.content = self.company_management_screen

    def show_route_selection(self, widget):
        self.main_window.content = self.route_selection_screen

    def upload_selected(self, widget):
        # Get selected indices from checkboxes
        selected = []
        for i, checkbox in enumerate(self.checkboxes):
            if checkbox.value:
                selected.append(i)

        if not selected:
            self.show_dialog_async("info",
                                   "No Selection",
                                   "Please select pick up forms to upload"
                                   )
            return

        try:
            with open(self.data_file, "r") as f:
                all_pos = json.load(f)
        except Exception as e:
            self.show_dialog_async("error",
                                   "Error",
                                   f"Couldn't load data: {str(e)}"
                                   )
            return

        to_upload = []
        for i in selected:
            if i < len(all_pos):
                po = all_pos[i].copy()
                # Ensure all required fields are present
                if 'pickup_date' not in po:
                    po['pickup_date'] = datetime.now().strftime("%m/%d/%Y")
                if 'driver_id' not in po:
                    po['driver_id'] = self.driver_id
                # Make sure 'uploaded' is boolean (not string "yes"/"no")
                if po.get('uploaded') == "yes":
                    po['uploaded'] = True
                elif po.get('uploaded') == "no":
                    po['uploaded'] = False
                to_upload.append(po)

        async def do_upload():
            self.show_loading("Uploading...")
            try:
                def _post():
                    return requests.post(self.upload_url, json=to_upload, timeout=30)
                response = await asyncio.to_thread(_post)
                if response.status_code == 200:
                    # Mark as uploaded
                    for i in selected:
                        if i < len(all_pos):
                            all_pos[i]["uploaded"] = True
                    with open(self.data_file, "w") as f:
                        json.dump(all_pos, f, indent=2)
                    self.load_pos()
                    self.show_dialog_async("info", "Success", f"{len(to_upload)} pick up form(s) uploaded successfully!")
                else:
                    self.show_dialog_async("error", "Error", f"Server responded: {response.status_code}\n{response.text}")
            except Exception as e:
                print(f"DEBUG: Upload exception: {str(e)}")
                import traceback
                traceback.print_exc()
                self.show_dialog_async("error", "Error", f"Upload failed: {str(e)}")
            finally:
                self.hide_loading()

        asyncio.create_task(do_upload())

    def delete_selected(self, widget):
        # Get selected indices from checkboxes
        selected = []
        for i, checkbox in enumerate(self.checkboxes):
            if checkbox.value:
                selected.append(i)

        if not selected:
            self.show_dialog_async("info",
                                   "No Selection",
                                   "Please select pick up forms to delete"
                                   )
            return

        try:
            with open(self.data_file, "r") as f:
                pos = json.load(f)
        except Exception as e:
            self.show_dialog_async("error",
                                   "Error",
                                   f"Couldn't load data: {str(e)}"
                                   )
            return

        # Delete in reverse order
        for i in sorted(selected, reverse=True):
            if i < len(pos):
                pos.pop(i)

        try:
            with open(self.data_file, "w") as f:
                json.dump(pos, f, indent=2)

            self.load_pos()
            self.show_dialog_async("info",
                                   "Success",
                                   f"{len(selected)} pick up form(s) deleted!"
                                   )
        except Exception as e:
            self.show_dialog_async("error",
                                   "Error",
                                   f"Delete failed: {str(e)}"
                                   )

    def update_selected(self, widget):
        # Get selected indices from checkboxes
        selected = []
        for i, checkbox in enumerate(self.checkboxes):
            if checkbox.value:
                selected.append(i)

        if len(selected) != 1:
            self.show_dialog_async("info",
                                   "Invalid Selection",
                                   "Please select exactly one pick up form to update"
                                   )
            return

        try:
            with open(self.data_file, "r") as f:
                pos = json.load(f)
        except Exception as e:
            self.show_dialog_async("error",
                                   "Error",
                                   f"Couldn't load data: {str(e)}"
                                   )
            return

        if selected[0] >= len(pos):
            self.show_dialog_async("error",
                                   "Error",
                                   "Invalid pick up form selected"
                                   )
            return

        # Load PO data into form
        po_data = pos[selected[0]].copy()
        self.editing_index = selected[0]

        # POPULATE THE FORM FIELDS - THIS WAS MISSING
        if hasattr(self, 'selected_info_label'):
            self.selected_info_label.text = f"{po_data.get('route', '')} | {po_data.get('company', '')}"

        # Update the add PO screen with the data
        self.update_add_po_screen()

        # Now populate the form fields with the selected PO data
        if hasattr(self, 'blade_dropdown'):
            # Set the description in the dropdown or custom field
            description = po_data.get('description', '')
            if description in self.frequent_blades:
                # It's a frequent blade
                self.blade_dropdown.value = description
                if hasattr(self, 'custom_desc_container'):
                    self.custom_desc_container.visible = False
                    self.custom_desc_input.value = ""
            else:
                # It's a custom description
                self.blade_dropdown.value = "--- Enter Custom Description ---"
                if hasattr(self, 'custom_desc_container'):
                    self.custom_desc_container.visible = True
                    self.custom_desc_input.value = description

        if hasattr(self, 'qty_input'):
            self.qty_input.value = str(po_data.get('quantity', ''))

        if hasattr(self, 'date_label'):
            pickup_date = po_data.get('pickup_date', datetime.now().strftime("%m/%d/%Y"))
            self.date_label.text = f"Pickup Date: {pickup_date}"

        # IMPORTANT: Also update selected company if different
        company = po_data.get('company', '')
        if company and company != self.selected_company:
            self.selected_company = company
            self.save_settings()
            self.update_frequent_blades_list()

        # Show the add PO screen in edit mode
        self.main_window.content = self.add_po_screen

    def select_all_pos(self, widget):
        """Select all POs (turn on all switches in the pickup list)."""
        try:
            total = 0
            for cb in getattr(self, 'checkboxes', []) or []:
                cb.value = True
                total += 1
            if total == 0:
                self.show_dialog_async("info", "No Items", "There are no pick up forms to select.")
        except Exception as e:
            print(f"Select All error: {e}")

    def handle_back(self):
        """Handle Android hardware back key. Return True if consumed."""
        try:
            content = getattr(self.main_window, 'content', None)
            # If on add PO screen, go back to home in current mode
            if content is getattr(self, 'add_po_screen', None):
                self.show_home()
                return True
            # If on route/company selection or settings/management, go to current home
            if content in [
                getattr(self, 'route_selection_screen', None),
                getattr(self, 'delivery_route_screen', None),
                getattr(self, 'settings_screen', None),
                getattr(self, 'company_management_screen', None),
            ]:
                self.show_current_home()
                return True
            # If in delivery mode and not on delivery home, navigate there
            if self.app_mode == 'delivery' and content is not getattr(self, 'delivery_home_screen', None):
                self.show_delivery_home()
                return True
            # If in pickup mode and not on pickup home, navigate there
            if self.app_mode == 'pickup' and content is not getattr(self, 'pickup_home_screen', None):
                self.show_home()
                return True
        except Exception as e:
            print(f"handle_back error: {e}")
        return False

    def enable_android_back(self):
        """Register an Android View.OnKeyListener to catch the hardware back button."""
        if not ANDROID:
            return
        try:
            from jnius import autoclass, PythonJavaClass, java_method

            class _OnKeyListener(PythonJavaClass):
                __javainterfaces__ = ['android/view/View$OnKeyListener']
                __javacontext__ = 'app'

                def __init__(self, py_app):
                    super().__init__()
                    self.py_app = py_app

                @java_method('(Landroid/view/View;ILandroid/view/KeyEvent;)Z')
                def onKey(self, v, keyCode, event):
                    KeyEvent = autoclass('android.view.KeyEvent')
                    # Consume only back key on action up
                    if keyCode == KeyEvent.KEYCODE_BACK and event.getAction() == KeyEvent.ACTION_UP:
                        try:
                            return True if self.py_app.handle_back() else False
                        except Exception as e:
                            print(f"OnKey handler error: {e}")
                            return False
                    return False

            try:
                # Try getting the activity via android.mActivity
                from android import mActivity
                activity = mActivity
            except Exception:
                # Fallback to Kivy's PythonActivity if available
                activity = autoclass('org.kivy.android.PythonActivity').mActivity

            window = activity.getWindow()
            decor = window.getDecorView()
            listener = _OnKeyListener(self)
            decor.setFocusableInTouchMode(True)
            decor.requestFocus()
            decor.setOnKeyListener(listener)
            print("Android back button handler enabled")
        except Exception as e:
            print(f"Failed to register Android back handler: {e}")

    def check_for_updates(self, silent=False):
        """
        Check for newer versions of the app on the server without blocking UI
        """
        async def _check():
            if not silent:
                self.show_loading("Checking for updates...")
            try:
                def _get():
                    return requests.get(self.update_check_url, timeout=10)
                response = await asyncio.to_thread(_get)
                if response.status_code != 200:
                    if not silent:
                        self.show_dialog_async("info", "Update Check Failed",
                                               "Could not connect to update server.\n\nPlease check your internet connection and try again.")
                    return

                pattern = r'<a href="(Pick Up Form-(\d+\.\d+\.\d+)-universal\.apk)">'
                matches = re.findall(pattern, response.text)
                if not matches:
                    if not silent:
                        self.show_dialog_async("info", "No Updates Found", "No update files found on server.")
                    return

                file_info = []
                for full_match in matches:
                    filename = full_match[0]
                    version_num = full_match[1]
                    encoded_filename = filename.replace(" ", "%20")
                    file_info.append({
                        'filename': filename,
                        'version': version_num,
                        'download_url': f"{self.update_check_url}{encoded_filename}"
                    })

                latest_info = max(file_info, key=lambda x: version.parse(x['version']))
                latest_version = latest_info['version']
                latest_filename = latest_info['filename']
                download_url = latest_info['download_url']

                if version.parse(latest_version) > version.parse(self.current_version):
                    self.latest_version = latest_version
                    self.latest_filename = latest_filename
                    self.download_url = download_url

                    update_message = (
                        f"✨ New Version Available!\n\n"
                        f"📱 Current: v{self.current_version}\n"
                        f"🚀 Latest: v{latest_version}\n\n"
                        f"Would you like to download and install the update now?"
                    )

                    async def show_update_dialog():
                        result = await self.main_window.dialog(
                            toga.ConfirmDialog(
                                title="Update Available",
                                message=update_message
                            )
                        )
                        if result:
                            self.handle_update_confirmation(True)
                        else:
                            self.handle_update_confirmation(False)

                    asyncio.create_task(show_update_dialog())
                else:
                    if not silent:
                        self.show_dialog_async("info", "✅ Up to Date",
                                               f"You're running the latest version!\n\nVersion: v{self.current_version}")
            except Exception as e:
                print(f"Error checking for updates: {e}")
                import traceback
                traceback.print_exc()
                if not silent:
                    self.show_dialog_async("error", "❌ Update Failed", f"An unexpected error occurred:\n{str(e)}")
            finally:
                if not silent:
                    self.hide_loading()
        asyncio.create_task(_check())

    def handle_update_confirmation(self, response):
        """Handle user response to update confirmation"""
        if response:
            # User wants to update - start download
            asyncio.create_task(self.download_and_install_update())
        else:
            # User declined update
            self.show_dialog_async("info",
                                   "Update Declined",
                                   "You can check for updates later in the Settings menu."
                                   )

    def _try_auto_install_apk(self, apk_path):
        """
        Try to install the APK programmatically.
        Returns (True, None) on success (installer Intent launched).
        Returns (False, error_message) on failure.
        """
        if not ANDROID:
            return False, "Not running on Android"

        try:
            # Simple approach: Use Android's system intent
            # This will work if the user has enabled "Install unknown apps" for this app

            # First check if APK exists
            if not os.path.exists(apk_path):
                return False, f"APK file not found: {apk_path}"

            # Try to use Java/Android API via jnius if available
            try:
                from jnius import autoclass

                # Get Android classes
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                Intent = autoclass('android.content.Intent')
                Uri = autoclass('android.net.Uri')
                File = autoclass('java.io.File')

                activity = PythonActivity.mActivity

                # Check if file exists
                apk_file = File(apk_path)
                if not apk_file.exists():
                    return False, f"APK file not found: {apk_path}"

                # Try to get package name for FileProvider
                package_name = activity.getPackageName()

                # Create URI
                try:
                    # Try FileProvider first (Android 7.0+)
                    FileProvider = autoclass('androidx.core.content.FileProvider')
                    authority = f"{package_name}.fileprovider"
                    content_uri = FileProvider.getUriForFile(
                        activity,
                        authority,
                        apk_file
                    )
                    uri = content_uri
                    use_fileprovider = True
                except:
                    # Fallback to file:// URI
                    uri = Uri.fromFile(apk_file)
                    use_fileprovider = False

                # Create install intent
                install_intent = Intent(Intent.ACTION_INSTALL_PACKAGE)
                install_intent.setData(uri)

                if use_fileprovider:
                    install_intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

                install_intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                install_intent.putExtra(Intent.EXTRA_NOT_UNKNOWN_SOURCE, True)

                # Start installation
                activity.startActivity(install_intent)
                return True, None

            except ImportError:
                # jnius not available - use a simpler approach
                # This might not work on newer Android versions

                # Try to use Android's package installer via adb-like command
                # Note: This requires the app to have INSTALL_PACKAGES permission
                import subprocess

                try:
                    # This command tries to install the APK
                    result = subprocess.run(
                        ['su', '-c', f'pm install -r {apk_path}'],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )

                    if 'Success' in result.stdout:
                        return True, None
                    else:
                        return False, f"Install failed: {result.stdout} {result.stderr}"
                except:
                    # Fallback: Just tell user to install manually
                    return False, "Please install manually via file manager"

            except Exception as e:
                return False, f"Install error: {str(e)}"

        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, str(e)

    async def show_permission_explanation(self):
        """Show explanation for why permissions are needed"""
        message = (
            "This app needs the following permissions:\n\n"
            "• Storage: To save PDF receipts and download updates\n"
            "• Internet: To sync data with the server\n"
            "• Install apps: To update the app when new versions are available\n\n"
            "Please grant these permissions when prompted."
        )

        await self.main_window.dialog(
            toga.InfoDialog(
                title="Permissions Required",
                message=message
            )
        )

    async def download_and_install_update(self):
        import os
        import asyncio
        from pathlib import Path
        import toga
        import requests

        # ----------------------------
        # Save current UI
        # ----------------------------
        original_content = self.main_window.content

        progress_bar = toga.ProgressBar(max=100)
        progress_bar.value = 0

        status_label = toga.Label(
            "Downloading update... 0%",
            style=toga.style.Pack(padding_bottom=10),
        )

        loading_box = toga.Box(
            children=[status_label, progress_bar],
            style=toga.style.Pack(
                direction="column",
                alignment="center",
                padding=20,
            ),
        )

        self.main_window.content = loading_box

        try:
            loop = asyncio.get_running_loop()

            # ----------------------------
            # Background download
            # ----------------------------
            def _download():
                response = requests.get(self.download_url, stream=True, timeout=60)
                response.raise_for_status()

                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0
                data = bytearray()

                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue

                    data.extend(chunk)
                    downloaded += len(chunk)

                    if total_size > 0:
                        percent = int((downloaded / total_size) * 100)
                        asyncio.run_coroutine_threadsafe(
                            _update_progress(percent),
                            loop,
                        )

                return bytes(data)

            async def _update_progress(percent):
                progress_bar.value = percent
                status_label.text = f"Downloading update... {percent}%"

            apk_bytes = await asyncio.to_thread(_download)

            # ----------------------------
            # Resolve save location
            # ----------------------------
            downloads_dir = None

            if ANDROID:
                for path in (
                        "/storage/emulated/0/Download",
                        "/sdcard/Download",
                        "/storage/self/primary/Download",
                ):
                    if os.path.exists(path):
                        downloads_dir = Path(path)
                        break

            if not downloads_dir:
                downloads_dir = Path(self.data_dir) / "downloads"

            downloads_dir.mkdir(parents=True, exist_ok=True)
            apk_path = downloads_dir / self.latest_filename

            await asyncio.to_thread(apk_path.write_bytes, apk_bytes)

            file_size_mb = len(apk_bytes) / (1024 * 1024)

            # ----------------------------
            # Restore UI
            # ----------------------------
            self.main_window.content = original_content

            self.show_dialog_async(
                "info",
                "Download Complete",
                (
                    f"✅ Update downloaded.\n\n"
                    f"Version: v{self.latest_version}\n"
                    f"Size: {file_size_mb:.1f} MB\n\n"
                    f"Saved to:\n{apk_path}\n\n"
                    f"To install:\n"
                    f"1. Open your file manager\n"
                    f"2. Go to Downloads\n"
                    f"3. Tap {self.latest_filename}"
                ),
            )

        except Exception as e:
            import traceback
            traceback.print_exc()

            self.main_window.content = original_content

            self.show_dialog_async(
                "error",
                "Download Failed",
                f"Failed to download update:\n{str(e)}",
            )

    class AndroidPermissions:
        """Helper class for Android permissions handling - SIMPLIFIED VERSION"""

        @staticmethod
        async def request_storage_permission():
            """Request storage permission for Android - Simplified version"""
            if not ANDROID:
                return True

            # In Chaquopy/Toga 5.3, we can't request permissions directly via Python
            # The app should have these permissions from the manifest
            # We'll just try to write a test file to check if we have permission

            try:
                # Try to write a test file to check permissions
                test_dir = "/storage/emulated/0/Download"
                if not os.path.exists(test_dir):
                    test_dir = "/sdcard/Download"

                if os.path.exists(test_dir):
                    test_file = os.path.join(test_dir, "permission_test.txt")
                    with open(test_file, "w") as f:
                        f.write("test")
                    os.remove(test_file)
                    return True
                else:
                    # Try app's private storage
                    import tempfile
                    with tempfile.NamedTemporaryFile(mode="w", delete=True) as f:
                        f.write("test")
                    return True
            except:
                # We probably don't have storage permission
                return False

        @staticmethod
        async def request_install_permission():
            """Request install permission for Android 8.0+ - Simplified version"""
            if not ANDROID:
                return True

            # In Chaquopy, we can't request this permission directly
            # The system will prompt the user when we try to install
            # Just return True and let the installation attempt handle it
            return True


def main():
    return POApp()
