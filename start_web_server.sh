#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found!"
    echo "Please run install.sh first or create a virtual environment:"
    echo "  python3 -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Check if Flask is installed
if ! python3 -c "import flask" 2>/dev/null; then
    echo "❌ Flask is not installed!"
    echo "Please install dependencies:"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

# Print startup information
echo "========================================="
echo "Starting GPS NTP Web Server"
echo "========================================="
echo "Virtual Environment: $SCRIPT_DIR/venv"
echo "Python: $(which python3)"
echo ""

# Run web server with any passed arguments
python3 web_server.py "$@"
