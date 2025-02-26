function saveInvoice() {
    // Collect invoice data
    const invoiceData = {
        date: document.getElementById('invoice-date').value,
        customer_id: document.getElementById('customer-select').value,
        customer_name: document.getElementById('customer-select').options[document.getElementById('customer-select').selectedIndex]?.text || '',
        items: [],
        total_amount: 0,
        total_items: 0
    };

    // Get all invoice items
    const rows = document.querySelectorAll('#invoice-items tbody tr:not(.empty-row)');
    rows.forEach(row => {
        if (row.querySelector('.product-select').value) {
            const item = {
                product_id: parseInt(row.querySelector('.product-select').value),
                quantity: parseFloat(row.querySelector('.quantity').value),
                price: parseFloat(row.querySelector('.price').value),
                amount: parseFloat(row.querySelector('.amount').value)
            };
            invoiceData.items.push(item);
            invoiceData.total_amount += item.amount;
            invoiceData.total_items += item.quantity;
        }
    });

    // Save invoice
    fetch('/new_invoice', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(invoiceData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Redirect to new invoice page
            window.location.href = '/new_invoice';
        } else {
            alert('Error saving invoice: ' + data.error);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error saving invoice');
    });
}

function saveEditInvoice() {
    // Collect invoice data
    const invoiceData = {
        id: document.getElementById('invoice-id').value,
        date: document.getElementById('invoice-date').value,
        customer_id: document.getElementById('customer-select').value,
        customer_name: document.getElementById('customer-select').options[document.getElementById('customer-select').selectedIndex]?.text || '',
        items: [],
        total_amount: 0,
        total_items: 0
    };

    // Get all invoice items
    const rows = document.querySelectorAll('#invoice-items tbody tr:not(.empty-row)');
    rows.forEach(row => {
        if (row.querySelector('.product-select').value) {
            const item = {
                product_id: parseInt(row.querySelector('.product-select').value),
                quantity: parseFloat(row.querySelector('.quantity').value),
                price: parseFloat(row.querySelector('.price').value),
                amount: parseFloat(row.querySelector('.amount').value)
            };
            invoiceData.items.push(item);
            invoiceData.total_amount += item.amount;
            invoiceData.total_items += item.quantity;
        }
    });

    // Save edited invoice
    fetch(`/invoices/${invoiceData.id}/edit`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(invoiceData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Redirect to new invoice page instead of invoices list
            window.location.href = '/new_invoice';
        } else {
            alert('Error saving invoice: ' + data.error);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error saving invoice');
    });
} 