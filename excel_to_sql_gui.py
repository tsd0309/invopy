import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import pandas as pd
from datetime import datetime
import os

class ExcelToSQLApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Excel to SQL Converter")
        self.root.geometry("800x600")
        self.root.resizable(True, True)
        
        # Configure style
        style = ttk.Style()
        style.configure('TButton', padding=5)
        style.configure('Header.TLabel', font=('Arial', 12, 'bold'))
        
        # Create main frame
        main_frame = ttk.Frame(root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # Header
        header = ttk.Label(
            main_frame, 
            text="Excel to SQL Converter for Products", 
            style='Header.TLabel'
        )
        header.grid(row=0, column=0, columnspan=3, pady=10)
        
        # File selection
        ttk.Label(main_frame, text="Excel File:").grid(
            row=1, column=0, sticky=tk.W, pady=5
        )
        self.file_path = tk.StringVar()
        self.file_entry = ttk.Entry(
            main_frame, 
            textvariable=self.file_path, 
            width=50
        )
        self.file_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5)
        
        browse_btn = ttk.Button(
            main_frame, 
            text="Browse", 
            command=self.browse_file
        )
        browse_btn.grid(row=1, column=2, padx=5)
        
        # Convert button
        convert_btn = ttk.Button(
            main_frame, 
            text="Convert to SQL", 
            command=self.convert_file
        )
        convert_btn.grid(row=2, column=0, columnspan=3, pady=10)
        
        # SQL Output
        ttk.Label(main_frame, text="Generated SQL:").grid(
            row=3, column=0, sticky=tk.W
        )
        self.sql_output = scrolledtext.ScrolledText(
            main_frame, 
            wrap=tk.WORD, 
            width=80, 
            height=20
        )
        self.sql_output.grid(
            row=4, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S)
        )
        
        # Copy button
        copy_btn = ttk.Button(
            main_frame, 
            text="Copy SQL", 
            command=self.copy_sql
        )
        copy_btn.grid(row=5, column=0, columnspan=3, pady=10)
        
        # Status bar
        self.status_var = tk.StringVar()
        self.status_bar = ttk.Label(
            main_frame, 
            textvariable=self.status_var, 
            relief=tk.SUNKEN
        )
        self.status_bar.grid(
            row=6, column=0, columnspan=3, sticky=(tk.W, tk.E)
        )
        
        # Configure resizing
        for i in range(7):
            main_frame.rowconfigure(i, weight=1 if i == 4 else 0)
    
    def browse_file(self):
        """Open file dialog to select Excel file"""
        filetypes = (
            ('Excel files', '*.xlsx *.xls'),
            ('All files', '*.*')
        )
        filename = filedialog.askopenfilename(
            title='Select Excel File',
            filetypes=filetypes
        )
        if filename:
            self.file_path.set(filename)
            self.status_var.set("File selected: " + os.path.basename(filename))
    
    def clean_string(self, value):
        """Clean and escape string values for SQL"""
        if pd.isna(value):
            return 'NULL'
        return f"'{str(value).strip().replace(chr(39), chr(39)+chr(39))}'"
    
    def convert_file(self):
        """Convert Excel file to SQL command"""
        if not self.file_path.get():
            messagebox.showerror("Error", "Please select an Excel file first")
            return
        
        try:
            # Clear previous output
            self.sql_output.delete(1.0, tk.END)
            self.status_var.set("Converting...")
            self.root.update()
            
            # Read Excel file
            df = pd.read_excel(self.file_path.get())
            
            # Start building SQL command
            sql_command = "INSERT INTO product (item_code, description, tamil_name, uom, price, stock, restock_level, stock_locations, tags, notes) VALUES\n"
            values = []
            
            # Process each row
            for index, row in df.iterrows():
                # Handle NULL values and string escaping
                item_code = self.clean_string(row['Item Code'])
                description = self.clean_string(row['Description'])
                tamil_name = self.clean_string(row['Tamil Name'])
                uom = self.clean_string(row['UOM'])
                price = str(row['Price']) if pd.notna(row['Price']) else '0'
                stock = str(int(row['Stock'])) if pd.notna(row['Stock']) else '0'
                restock_level = str(int(row['Restock Level'])) if pd.notna(row['Restock Level']) else '0'
                stock_locations = self.clean_string(row['Stock Locations'])
                tags = self.clean_string(row['Tags'])
                notes = self.clean_string(row['Notes'])
                
                # Create value tuple
                value = f"({item_code}, {description}, {tamil_name}, {uom}, {price}, {stock}, {restock_level}, {stock_locations}, {tags}, {notes})"
                values.append(value)
            
            # Join values and complete SQL command
            sql_command += ",\n".join(values) + ";"
            
            # Show in text area
            self.sql_output.insert(tk.END, sql_command)
            
            # Update status
            self.status_var.set(f"Converted {len(values)} products successfully")
            
        except pd.errors.EmptyDataError:
            messagebox.showerror("Error", "The Excel file is empty")
        except KeyError as e:
            messagebox.showerror("Error", f"Missing required column: {e}")
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {str(e)}")
    
    def copy_sql(self):
        """Copy SQL command to clipboard"""
        sql_text = self.sql_output.get(1.0, tk.END).strip()
        if sql_text:
            self.root.clipboard_clear()
            self.root.clipboard_append(sql_text)
            self.status_var.set("SQL command copied to clipboard!")
        else:
            messagebox.showwarning("Warning", "No SQL command to copy")

def main():
    root = tk.Tk()
    app = ExcelToSQLApp(root)
    root.mainloop()

if __name__ == "__main__":
    main() 