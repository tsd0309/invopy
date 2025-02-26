# Inventory Management System

A modern, responsive inventory management system built with Flask and Progressive Web App (PWA) capabilities.

## Features

- 📱 Progressive Web App (PWA) with offline support
- 🚀 Fast and responsive interface
- 📦 Product management
- 📝 Invoice generation
- 👥 Customer management
- 📊 Reports and analytics
- 🔒 User authentication and permissions
- 🌙 Dark mode support
- 📱 Mobile-friendly design

## Tech Stack

- Python 3.11+
- Flask
- SQLAlchemy
- PostgreSQL
- Bootstrap 5
- Service Workers for PWA
- Modern JavaScript

## Installation

1. Clone the repository:
```bash
git clone [your-repo-url]
cd inventory-system
```

2. Create and activate virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your database credentials and settings
```

5. Initialize the database:
```bash
flask db upgrade
```

6. Run the application:
```bash
flask run
```

## Development

- The application uses Flask for the backend
- SQLAlchemy for database ORM
- Service workers for PWA functionality
- Bootstrap 5 for responsive UI

## Deployment

The application is configured for deployment on Render.com using the following:
- Gunicorn as the WSGI server
- PostgreSQL database
- Environment variables for configuration

## License

MIT License - See LICENSE file for details

## Usage

### Products Management

1. Click on "Products" in the navigation menu
2. Use the "Add New Product" button to create products
3. Edit or delete existing products using the action buttons

### Creating Invoices

1. Click on "New Invoice" in the navigation menu
2. Fill in the customer details
3. Add products to the invoice using the "Add Item" button
4. The system will automatically calculate totals
5. Click "Save Invoice" to generate the invoice

### Viewing and Printing Invoices

1. Click on "Invoices" in the navigation menu
2. Use the "View" button to see invoice details
3. Use the "Print" button to get a printer-friendly version

## Database

The application uses SQLite as its database. The database file (`inventory.db`) will be created automatically when you first run the application.

## Security

- The application includes CSRF protection
- SQL injection protection through SQLAlchemy
- Input validation and sanitization
- Error handling and logging

## Contributing

1. Fork the repository
2. Create a new branch for your feature
3. Commit your changes
4. Push to the branch
5. Create a new Pull Request
