#!/bin/bash
pip install -r requirements.txt
python -m flask db upgrade
echo "Build completed successfully!" 