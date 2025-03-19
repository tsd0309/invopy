import pandas as pd
import sys
from datetime import datetime

def clean_string(value):
    """Clean and escape string values for SQL"""
    if pd.isna(value):
        return 'NULL'
    return f"'{str(value).strip().replace(chr(39), chr(39)+chr(39))}'"

def excel_to_sql_insert(excel_file):
    try:
        # Read the Excel file
        df = pd.read_excel(excel_file)
        
        # Start building the SQL command
        sql_command = "INSERT INTO product (item_code, description, tamil_name, uom, price, stock, restock_level, stock_locations, tags, notes) VALUES\n"
        values = []
        
        # Process each row
        for index, row in df.iterrows():
            # Handle NULL values and string escaping
            item_code = clean_string(row['Item Code'])
            description = clean_string(row['Description'])
            tamil_name = clean_string(row['Tamil Name'])
            uom = clean_string(row['UOM'])
            price = str(row['Price']) if pd.notna(row['Price']) else '0'
            stock = str(int(row['Stock'])) if pd.notna(row['Stock']) else '0'
            restock_level = str(int(row['Restock Level'])) if pd.notna(row['Restock Level']) else '0'
            stock_locations = clean_string(row['Stock Locations'])
            tags = clean_string(row['Tags'])
            notes = clean_string(row['Notes'])
            
            # Create the value tuple
            value = f"({item_code}, {description}, {tamil_name}, {uom}, {price}, {stock}, {restock_level}, {stock_locations}, {tags}, {notes})"
            values.append(value)
        
        # Join all values with commas
        sql_command += ",\n".join(values) + ";"
        
        # Generate output filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"product_import_{timestamp}.sql"
        
        # Write to file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(sql_command)
        
        print(f"SQL command has been generated in '{output_file}'")
        print(f"Total products processed: {len(values)}")
        
    except pd.errors.EmptyDataError:
        print("Error: The Excel file is empty")
        sys.exit(1)
    except KeyError as e:
        print(f"Error: Missing required column {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python excel_to_sql.py <excel_file>")
        print("Example: python excel_to_sql.py products.xlsx")
        sys.exit(1)
    
    excel_file = sys.argv[1]
    excel_to_sql_insert(excel_file) 