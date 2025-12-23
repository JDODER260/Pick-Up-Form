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

        self.current_version = "2.2.3"  # Updated version for new features

        # Data storage
        self.data_dir = None
        self.data_file = None
        self.settings_file = None
        self.company_db_file = None
        self.delivery_data_file = None

        # App state
        self.selected_route = ""
        self.selected_company = ""
        self.driver_id = ""
        self.app_mode = "delivery"  # Default to delivery mode: "delivery" or "pickup"

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

        asyncio.create_task(self.request_android_permissions())

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
        self.delivery_home_screen = self.create_delivery_home_screen
        self.pickup_home_screen = self.create_pickup_home_screen()
        self.add_po_screen = self.create_add_po_screen()

        # Set initial screen based on mode
        if not self.selected_route:
            self.main_window.content = self.route_selection_screen
        else:
            self.main_window.content = self.delivery_home_screen if self.app_mode == "delivery" else self.pickup_home_screen
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

    @property
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

        route_label = toga.Label(
            f"Route: {self.selected_route if self.selected_route else 'Not Selected'}",
            style=Pack(font_size=16, padding_bottom=5)
        )

        company_label = toga.Label(
            f"Company: {self.selected_company if self.selected_company else 'Not Selected'}",
            style=Pack(font_size=16, padding_bottom=5)
        )

        deliveries_label = toga.Label(
            f"Deliveries Loaded: {self.total_deliveries}",
            style=Pack(font_size=16, padding_bottom=5)
        )

        info_box.add(route_label)
        info_box.add(company_label)
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

        update_btn = toga.Button("Update", on_press=self.update_selected, style=Pack(flex=1, padding=5))
        settings_btn = toga.Button("Settings", on_press=self.show_settings, style=Pack(flex=1, padding=5))
        # No refresh button - replaced with mode switch

        row1.add(add_btn)
        row1.add(upload_btn)
        row1.add(delete_btn)

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

    def switch_to_pickup_mode(self, widget):
        """Switch from delivery to pickup mode"""
        self.app_mode = "pickup"
        self.save_settings()
        self.main_window.content = self.pickup_home_screen
        self.load_pos()

        # Update the company display immediately
        if hasattr(self, 'selection_label'):
            selection_text = f"{self.selected_route}"
            if self.selected_company:
                selection_text += f" | {self.selected_company}"
            self.selection_label.text = selection_text

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
            # Get PO numbers
            po_numbers = []
            for item in po_items:
                po_num = item.get('po_number', '')
                if po_num and str(po_num) not in po_numbers:
                    po_numbers.append(str(po_num))

            # Smaller column widths for half-letter
            info_col_widths = [0.8 * inch, 1.2 * inch, 0.8 * inch, 1.2 * inch]
            info_data = [
                ["Company:", company_name[:20] + ('...' if len(company_name) > 20 else ''),
                 "Pickup:", po_items[0].get('pickup_date', current_date)[:10] if po_items else current_date],
                ["Delivery:", current_date, "Custom:",
                 "_________________"]
            ]

            info_table = Table(info_data, colWidths=info_col_widths)
            info_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),  # Smaller font
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),  # Thinner lines
                ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                ('BACKGROUND', (2, 0), (2, -1), colors.lightgrey),
                # Enable word wrapping for all cells
                ('WORDWRAP', (0, 0), (-1, -1), True),
            ]))

            elements.append(info_table)
            elements.append(Spacer(1, 10))  # Less spacing

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
                "app_mode": self.app_mode
            }
            with open(self.settings_file, "w") as f:
                json.dump(settings, f, indent=2)
        except Exception as e:
            print(f"Error saving settings: {e}")

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
        """Select a company"""
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

        # Next button for step 1
        self.next_btn = toga.Button(
            "Next",
            on_press=self.go_to_step2,
            style=Pack(padding_top=10)
        )
        self.step1_box.add(self.next_btn)

        # Step 2: Quantity and auto-date (initially hidden)
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

        # Step 2 buttons
        step2_btn_box = toga.Box(style=Pack(direction=ROW, padding_top=10))

        self.back_btn = toga.Button(
            "Back",
            on_press=self.go_to_step1,
            style=Pack(flex=1, padding_right=5)
        )

        self.save_btn = toga.Button(
            "Save PO",
            on_press=self.save_po_form,
            style=Pack(flex=1, padding_left=5)
        )

        step2_btn_box.add(self.back_btn)
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

            row_box.add(checkbox)
            row_box.add(label)

            self.po_list_box.add(row_box)

    def reset_form(self):
        """Reset the add/update form"""
        self.editing_index = None

        # Update frequent blades list
        self.update_frequent_blades_list()

        # Update screen if it exists
        if hasattr(self, 'add_po_screen'):
            self.update_add_po_screen()

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
            # Clear current company and blade inputs
            self.new_company_input.value = ""
            self.new_blade_input.value = ""

            # Clear the blades list display
            self.blades_list.clear()

            # Update placeholder text to show selected route
            self.new_company_input.placeholder = f"Company for {selected_route}"

            # Optional: If you want to show existing companies in a dropdown
            # You could add a company dropdown here if needed
            print(f"Selected route for management: {selected_route}")

    def create_company_management_screen(self):
        """Create company database management screen"""
        main_box = toga.Box(style=Pack(direction=COLUMN, padding=10))

        title = toga.Label("Manage Company Database", style=Pack(font_size=24, padding_bottom=10))

        # Route management
        route_label = toga.Label("Add/Remove Route:", style=Pack(padding_bottom=5))

        route_box = toga.Box(style=Pack(direction=ROW, padding_bottom=10))
        self.new_route_input = toga.TextInput(
            placeholder="New route name",
            style=Pack(flex=1, padding_right=5)
        )
        add_route_btn = toga.Button(
            "Add Route",
            on_press=self.add_route,
            style=Pack(width=100)
        )
        route_box.add(self.new_route_input)
        route_box.add(add_route_btn)

        # Route selector for company management
        self.manage_route_dropdown = toga.Selection(
            items=self.available_routes,
            on_change=self.on_manage_route_change,
            style=Pack(padding_bottom=10)
        )

        # Company management
        company_label = toga.Label("Add/Remove Company:", style=Pack(padding_bottom=5))

        company_box = toga.Box(style=Pack(direction=ROW, padding_bottom=10))
        self.new_company_input = toga.TextInput(
            placeholder="New company name",
            style=Pack(flex=1, padding_right=5)
        )
        add_company_btn = toga.Button(
            "Add Company",
            on_press=self.add_company,
            style=Pack(width=100)
        )
        company_box.add(self.new_company_input)
        company_box.add(add_company_btn)

        # Frequent blades management for selected company
        blade_label = toga.Label("Add/Remove Frequent Blades:", style=Pack(padding_bottom=5))

        blade_box = toga.Box(style=Pack(direction=ROW, padding_bottom=10))
        self.new_blade_input = toga.TextInput(
            placeholder="New blade description",
            style=Pack(flex=1, padding_right=5)
        )
        add_blade_btn = toga.Button(
            "Add Blade",
            on_press=self.add_frequent_blade,
            style=Pack(width=100)
        )
        blade_box.add(self.new_blade_input)
        blade_box.add(add_blade_btn)

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
        main_box.add(route_box)
        main_box.add(self.manage_route_dropdown)
        main_box.add(company_label)
        main_box.add(company_box)
        main_box.add(blade_label)
        main_box.add(blade_box)
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
                self.show_dialog_async("info", "Success", f"Company '{new_company}' added")

    def add_frequent_blade(self, widget):
        """Add frequent blade to selected company"""
        selected_route = self.manage_route_dropdown.value or self.selected_route
        selected_company = self.new_company_input.value.strip()
        new_blade = self.new_blade_input.value.strip()

        if selected_route and selected_company and new_blade:
            if (selected_route in self.company_database and
                    selected_company in self.company_database[selected_route]):

                company_data = self.company_database[selected_route][selected_company]
                if "frequent_blades" not in company_data:
                    company_data["frequent_blades"] = []

                if new_blade not in company_data["frequent_blades"]:
                    company_data["frequent_blades"].append(new_blade)
                    self.new_blade_input.value = ""

                    # Update blades list display
                    self.update_blades_list(selected_route, selected_company)

    def save_company_changes(self, widget):
        """Save company database changes"""
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
                remove_btn = toga.Button(
                    "Remove",
                    on_press=lambda w, b=blade: self.remove_blade(route, company, b),
                    style=Pack(width=80)
                )
                blade_box.add(blade_label)
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

        # Reset step visibility
        if hasattr(self, 'step1_box'):
            self.step1_box.visible = True
        if hasattr(self, 'step2_box'):
            self.step2_box.visible = False

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

    # Keep the original methods for upload, delete, update, and checking updates
    # These would be similar to your original code

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

        try:
            print(f"DEBUG: Uploading {len(to_upload)} POs to {self.upload_url}")
            print(f"DEBUG: First PO data: {json.dumps(to_upload[0] if to_upload else {})}")

            response = requests.post(self.upload_url, json=to_upload, timeout=30)
            print(f"DEBUG: Response status: {response.status_code}")
            print(f"DEBUG: Response text: {response.text}")

            if response.status_code == 200:
                # Mark as uploaded
                for i in selected:
                    if i < len(all_pos):
                        all_pos[i]["uploaded"] = True

                with open(self.data_file, "w") as f:
                    json.dump(all_pos, f, indent=2)

                self.load_pos()
                self.show_dialog_async("info",
                                       "Success",
                                       f"{len(to_upload)} pick up form(s) uploaded successfully!"
                                       )
            else:
                self.show_dialog_async("error",
                                       "Error",
                                       f"Server responded: {response.status_code}\n{response.text}"
                                       )
        except Exception as e:
            print(f"DEBUG: Upload exception: {str(e)}")
            import traceback
            traceback.print_exc()
            self.show_dialog_async("error",
                                   "Error",
                                   f"Upload failed: {str(e)}"
                                   )

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

    def check_for_updates(self, silent=False):
        """
        Check for newer versions of the app on the server
        """
        # SIMPLE VERSION: Run everything synchronously
        # This will block the UI, but it's simple and works
        try:
            print("Checking for updates...")

            # Fetch the directory listing
            response = requests.get(self.update_check_url, timeout=10)
            if response.status_code != 200:
                if not silent:
                    self.show_dialog_async("info",
                                           "Update Check Failed",
                                           "Could not connect to update server.\n\n"
                                           "Please check your internet connection and try again."
                                           )
                return

            # Look for APK files
            pattern = r'<a href="(Pick Up Form-(\d+\.\d+\.\d+)-universal\.apk)">'
            matches = re.findall(pattern, response.text)

            if not matches:
                if not silent:
                    self.show_dialog_async("info",
                                           "No Updates Found",
                                           "No update files found on server."
                                           )
                return

            # Extract filenames and versions
            file_info = []
            for full_match in matches:
                filename = full_match[0]
                version_num = full_match[1]
                # Use encoded URL for download
                encoded_filename = filename.replace(" ", "%20")
                file_info.append({
                    'filename': filename,
                    'version': version_num,
                    'download_url': f"{self.update_check_url}{encoded_filename}"
                })

            # Find the latest version
            latest_info = max(file_info, key=lambda x: version.parse(x['version']))
            latest_version = latest_info['version']
            latest_filename = latest_info['filename']
            download_url = latest_info['download_url']

            print(f"Current: {self.current_version}, Latest: {latest_version}")
            print(f"Download URL: {download_url}")

            # Compare versions
            if version.parse(latest_version) > version.parse(self.current_version):
                # Update available
                self.latest_version = latest_version
                self.latest_filename = latest_filename
                self.download_url = download_url

                update_message = (
                    f"✨ New Version Available!\n\n"
                    f"📱 Current: v{self.current_version}\n"
                    f"🚀 Latest: v{latest_version}\n\n"
                    f"Would you like to download and install the update now?"
                )

                # Show confirm dialog using async - FIXED for Toga 5.2
                async def show_update_dialog():
                    # In Toga 5.2, use main_window.dialog() with a ConfirmDialog
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

                # Run the async dialog
                asyncio.create_task(show_update_dialog())
            else:
                if not silent:
                    self.show_dialog_async("info",
                                           "✅ Up to Date",
                                           f"You're running the latest version!\n\n"
                                           f"Version: v{self.current_version}"
                                           )

        except Exception as e:
            print(f"Error checking for updates: {e}")
            import traceback
            traceback.print_exc()

            if not silent:
                self.show_dialog_async("error",
                                       "❌ Update Failed",
                                       f"An unexpected error occurred:\n{str(e)}"
                                       )

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

    async def request_android_permissions(self):
        """Request Android permissions for Chaquopy/Toga 5.3"""
        if not ANDROID or not ANDROID_IMPORTS_WORKING:
            print("Not on Android or jnius not available")
            return True

        try:
            print("Requesting permissions via Chaquopy/jnius...")

            from jnius import autoclass, cast

            # Get necessary Android classes
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            Context = autoclass('android.content.Context')
            ActivityCompat = autoclass('androidx.core.app.ActivityCompat')
            PermissionChecker = autoclass('androidx.core.content.PermissionChecker')

            # Get current activity
            activity = PythonActivity.mActivity

            # Define permissions needed
            permissions = [
                "android.permission.READ_EXTERNAL_STORAGE",
                "android.permission.WRITE_EXTERNAL_STORAGE",
                "android.permission.INTERNET",
                "android.permission.ACCESS_NETWORK_STATE",
                "android.permission.REQUEST_INSTALL_PACKAGES",
            ]

            print(f"Checking {len(permissions)} permissions")

            # Check current permission status
            need_to_request = []
            for permission in permissions:
                result = PermissionChecker.checkSelfPermission(activity, permission)
                # 0 = PERMISSION_GRANTED, -1 = PERMISSION_DENIED
                if result != 0:
                    need_to_request.append(permission)
                    print(f"Need permission: {permission}")

            # Request permissions if needed
            if need_to_request:
                print(f"Requesting {len(need_to_request)} permissions...")

                # Convert to Java String array
                String = autoclass('java.lang.String')
                perm_array = autoclass('java.lang.reflect.Array')
                permissions_java = perm_array.newInstance(String, len(need_to_request))

                for i, perm in enumerate(need_to_request):
                    perm_array.set(permissions_java, i, String(perm))

                # Request permissions
                ActivityCompat.requestPermissions(
                    activity,
                    permissions_java,
                    1001  # Request code
                )

                print("Permission request dialog should appear")
                return True
            else:
                print("All permissions already granted")
                return True

        except Exception as e:
            print(f"Error requesting permissions in Chaquopy: {e}")
            import traceback
            traceback.print_exc()
            return False

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
        """Download the APK and attempt to install it with proper permissions"""
        try:
            print(f"Starting download: {self.download_url}")

            # Download the APK first (we'll try to install even without permissions)
            import requests
            response = requests.get(self.download_url, timeout=60)

            if response.status_code != 200:
                self.show_dialog_async("error", "Download Failed",
                                       f"Failed to download update. Status: {response.status_code}")
                return

            # Save to appropriate location
            # Try to use standard Android paths if available
            downloads_dir = None

            if ANDROID:
                # Try common Android download locations
                possible_paths = [
                    "/storage/emulated/0/Download",
                    "/sdcard/Download",
                    "/storage/self/primary/Download",
                ]

                for path in possible_paths:
                    if os.path.exists(path):
                        downloads_dir = Path(path)
                        break

            # Fallback to app's data directory
            if not downloads_dir:
                downloads_dir = Path(self.data_dir) / "downloads"

            downloads_dir.mkdir(parents=True, exist_ok=True)
            apk_path = downloads_dir / self.latest_filename

            with open(apk_path, "wb") as f:
                f.write(response.content)

            file_size_mb = len(response.content) / (1024 * 1024)
            print(f"Download complete: {apk_path} ({file_size_mb:.1f} MB)")

            # Attempt to install on Android
            if ANDROID:
                success, error = self._try_auto_install_apk(str(apk_path))

                if success:
                    success_message = (
                        f"✅ Update downloaded and installer launched.\n\n"
                        f"Version: v{self.latest_version}\n"
                        f"Size: {file_size_mb:.1f} MB\n\n"
                        "Follow the system prompts to complete the installation."
                    )
                    self.show_dialog_async("info", "Install Started", success_message)
                else:
                    # Show helpful message with the error
                    if "permission" in error.lower() or "enable" in error.lower():
                        # Permission-related error
                        fallback_message = (
                            f"✅ Update downloaded.\n\n"
                            f"Version: v{self.latest_version}\n"
                            f"Size: {file_size_mb:.1f} MB\n\n"
                            f"Saved to: {apk_path}\n\n"
                            f"To install:\n"
                            f"1. Open your file manager app\n"
                            f"2. Navigate to Downloads folder\n"
                            f"3. Tap on: {self.latest_filename}\n"
                            f"4. Allow installation from this source if prompted\n\n"
                            f"Error: {error}"
                        )
                    else:
                        # Other error
                        fallback_message = (
                            f"✅ Update downloaded.\n\n"
                            f"Version: v{self.latest_version}\n"
                            f"Size: {file_size_mb:.1f} MB\n\n"
                            f"Saved to: {apk_path}\n\n"
                            f"To install manually:\n"
                            f"1. Open your file manager\n"
                            f"2. Find the APK file\n"
                            f"3. Tap to install\n\n"
                            f"Error: {error}"
                        )
                    self.show_dialog_async("info", "Download Complete", fallback_message)
            else:
                # Not on Android
                self.show_dialog_async("info", "Download Complete",
                                       f"Update downloaded to: {apk_path}")

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.show_dialog_async("error", "Download Error",
                                   f"Failed to download update:\n{str(e)}")


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