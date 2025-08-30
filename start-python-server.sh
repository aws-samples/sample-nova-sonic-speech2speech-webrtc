#!/bin/bash

# Nova S2S WebRTC Python Server Startup Script
# Cross-platform script for Mac, Linux, and Windows (Git Bash/WSL)
# This script sets up the conda environment and starts the Python WebRTC server

set -e  # Exit on any error

# Colors for output (with Windows compatibility)
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    # Windows Git Bash - simpler color support
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
else
    # Unix-like systems (Mac, Linux, WSL)
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m' # No Color
fi

# Detect operating system
detect_os() {
    case "$OSTYPE" in
        darwin*)  OS="macos" ;;
        linux*)   OS="linux" ;;
        msys*)    OS="windows" ;;
        cygwin*)  OS="windows" ;;
        *)        OS="unknown" ;;
    esac
}

# Cross-platform path resolution
get_script_dir() {
    if [[ "$OS" == "windows" ]]; then
        # Windows Git Bash path handling
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -W 2>/dev/null || pwd)"
    else
        # Unix-like systems
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    fi
}

# Initialize OS detection and paths
detect_os
get_script_dir
PROJECT_ROOT="$SCRIPT_DIR"
PYTHON_SERVER_DIR="$PROJECT_ROOT/python-webrtc-server"
LOGS_DIR="$PROJECT_ROOT/logs"

# Default configuration
DEFAULT_REGION="ap-northeast-1"
DEFAULT_CHANNEL="nova-s2s-webrtc-test"
DEFAULT_MODEL="amazon.nova-sonic-v1:0"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check conda installation with cross-platform support
check_conda_installation() {
    # Check for conda command
    if command_exists conda; then
        CONDA_VERSION=$(conda --version | cut -d' ' -f2)
        print_success "Conda $CONDA_VERSION detected on $OS"
        
        # Initialize conda for shell integration
        print_status "Initializing conda shell integration..."
        eval "$(conda shell.bash hook 2>/dev/null)" || {
            print_warning "Failed to initialize conda shell hook, trying alternative method..."
            # Try to source conda.sh directly
            if [[ -f "$CONDA_PREFIX/../etc/profile.d/conda.sh" ]]; then
                source "$CONDA_PREFIX/../etc/profile.d/conda.sh"
            elif [[ -f "/opt/homebrew/Caskroom/miniconda/base/etc/profile.d/conda.sh" ]]; then
                source "/opt/homebrew/Caskroom/miniconda/base/etc/profile.d/conda.sh"
            elif [[ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]]; then
                source "$HOME/miniconda3/etc/profile.d/conda.sh"
            elif [[ -f "/usr/local/miniconda3/etc/profile.d/conda.sh" ]]; then
                source "/usr/local/miniconda3/etc/profile.d/conda.sh"
            fi
        }
        
        return 0
    else
        print_error "Conda is not installed or not in PATH"
        print_error "Please install Miniconda or Anaconda for your platform:"
        case "$OS" in
            "macos")
                print_error "  macOS: https://docs.conda.io/en/latest/miniconda.html#macos-installers"
                print_error "  Or use: brew install miniconda"
                ;;
            "linux")
                print_error "  Linux: https://docs.conda.io/en/latest/miniconda.html#linux-installers"
                print_error "  Or use package manager: sudo apt install miniconda3 (Ubuntu/Debian)"
                ;;
            "windows")
                print_error "  Windows: https://docs.conda.io/en/latest/miniconda.html#windows-installers"
                print_error "  Make sure to add conda to PATH during installation"
                print_error "  Or use Windows Package Manager: winget install Anaconda.Miniconda3"
                ;;
        esac
        print_error ""
        print_error "After installation, restart your terminal and try again"
        print_error "Or use --fallback-venv to use Python venv instead (not recommended)"
        return 1
    fi
}

# Function to check Python version (fallback for venv)
check_python_version() {
    if command_exists python3; then
        PYTHON_CMD="python3"
    elif command_exists python; then
        PYTHON_CMD="python"
    else
        print_error "Python is not installed or not in PATH"
        return 1
    fi
    
    # Check Python version (requires 3.12+ for aws-sdk-bedrock-runtime)
    PYTHON_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    REQUIRED_VERSION="3.12"
    
    if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" = "$REQUIRED_VERSION" ]; then
        print_success "Python $PYTHON_VERSION detected"
        return 0
    else
        print_error "Python $PYTHON_VERSION detected, but Python $REQUIRED_VERSION or higher is required"
        return 1
    fi
}

# Function to activate conda environment with cross-platform support
activate_conda_environment() {
    local ENV_NAME="$1"
    
    print_status "Activating conda environment '$ENV_NAME'..."
    
    # Cross-platform conda activation
    case "$OS" in
        "windows")
            # Windows Git Bash conda activation
            if command -v conda >/dev/null 2>&1; then
                eval "$(conda shell.bash hook)" 2>/dev/null || true
                conda activate "$ENV_NAME" || {
                    print_error "Failed to activate conda environment '$ENV_NAME'"
                    print_error "Try running: conda activate $ENV_NAME"
                    return 1
                }
            else
                print_error "Conda not found in PATH on Windows"
                return 1
            fi
            ;;
        *)
            # Unix-like systems (Mac, Linux, WSL)
            if [[ -n "$CONDA_DEFAULT_ENV" ]] || command -v conda >/dev/null 2>&1; then
                conda activate "$ENV_NAME" || {
                    print_error "Failed to activate conda environment '$ENV_NAME'"
                    print_error "Try running: conda activate $ENV_NAME"
                    return 1
                }
            else
                # Try to initialize conda first
                eval "$(conda shell.bash hook 2>/dev/null)" || true
                conda activate "$ENV_NAME" || {
                    print_error "Failed to activate conda environment '$ENV_NAME'"
                    return 1
                }
            fi
            ;;
    esac
    
    print_success "Conda environment '$ENV_NAME' activated"
    
    # Verify activation
    if [[ "$CONDA_DEFAULT_ENV" == "$ENV_NAME" ]]; then
        print_success "Environment activation verified"
    else
        print_warning "Environment activation may not be complete"
        print_status "Current environment: ${CONDA_DEFAULT_ENV:-none}"
    fi
}

# Function to setup conda environment with cross-platform support
setup_conda_environment() {
    cd "$PYTHON_SERVER_DIR"
    
    local ENV_NAME="nova-s2s-webrtc"
    
    print_status "Setting up conda environment for $OS..."
    
    # Check if environment.yml exists
    if [ -f "environment.yml" ]; then
        print_status "Using environment.yml for conda setup..."
        
        # Check if conda environment exists
        if conda env list | grep -q "^$ENV_NAME "; then
            print_status "Conda environment '$ENV_NAME' already exists"
            print_status "Updating environment from environment.yml..."
            
            # Update with platform-specific handling
            case "$OS" in
                "windows")
                    conda env update -n "$ENV_NAME" -f environment.yml --prune || {
                        print_warning "Environment update failed, trying to recreate..."
                        conda env remove -n "$ENV_NAME" -y
                        conda env create -f environment.yml
                    }
                    ;;
                *)
                    conda env update -n "$ENV_NAME" -f environment.yml --prune
                    ;;
            esac
        else
            print_status "Creating conda environment from environment.yml..."
            conda env create -f environment.yml
            print_success "Conda environment created successfully"
        fi
    else
        # Fallback to manual creation
        print_warning "environment.yml not found, creating environment manually..."
        
        # Check if conda environment exists
        if conda env list | grep -q "^$ENV_NAME "; then
            print_status "Conda environment '$ENV_NAME' already exists"
        else
            print_status "Creating conda environment '$ENV_NAME' with Python 3.12..."
            conda create -n "$ENV_NAME" python=3.12 -y
            print_success "Conda environment created"
        fi
        
        # Activate and install essential packages
        activate_conda_environment "$ENV_NAME"
        
        # Install conda-forge packages (better cross-platform support)
        print_status "Installing essential packages via conda-forge..."
        conda install -c conda-forge aiortc ffmpeg pkg-config -y
        
        # Install pip packages
        print_status "Installing additional packages via pip..."
        pip install boto3 websockets python-dotenv aiohttp numpy opencv-python Pillow
        
        return 0
    fi
    
    # Activate conda environment
    activate_conda_environment "$ENV_NAME"
}

# Function to check and create virtual environment with cross-platform support
setup_virtual_environment() {
    cd "$PYTHON_SERVER_DIR"
    
    print_status "Setting up Python virtual environment for $OS..."
    
    if [ ! -d ".venv" ]; then
        print_status "Creating Python virtual environment..."
        $PYTHON_CMD -m venv .venv
        print_success "Virtual environment created"
    else
        print_status "Virtual environment already exists"
    fi
    
    # Cross-platform virtual environment activation
    print_status "Activating virtual environment..."
    case "$OS" in
        "windows")
            # Windows Git Bash activation
            if [ -f ".venv/Scripts/activate" ]; then
                source .venv/Scripts/activate
            elif [ -f ".venv/bin/activate" ]; then
                source .venv/bin/activate
            else
                print_error "Virtual environment activation script not found"
                return 1
            fi
            ;;
        *)
            # Unix-like systems
            if [ -f ".venv/bin/activate" ]; then
                source .venv/bin/activate
            else
                print_error "Virtual environment activation script not found"
                return 1
            fi
            ;;
    esac
    
    # Verify activation
    if [[ "$VIRTUAL_ENV" == *".venv"* ]]; then
        print_success "Virtual environment activated successfully"
    else
        print_warning "Virtual environment activation may not be complete"
    fi
    
    # Upgrade pip
    print_status "Upgrading pip..."
    python -m pip install --upgrade pip
}

# Function to install dependencies with cross-platform support
install_dependencies() {
    print_status "Installing Python dependencies for $OS..."
    
    # Check if requirements.txt exists (for venv fallback)
    if [ ! -f "requirements.txt" ] && [[ "$USE_VENV_FALLBACK" == "true" ]]; then
        print_error "requirements.txt not found in $PYTHON_SERVER_DIR"
        print_error "This is required when using --fallback-venv option"
        return 1
    fi
    
    # Install dependencies based on environment type
    if [[ "$USE_VENV_FALLBACK" == "true" ]]; then
        # Virtual environment - use requirements.txt
        print_status "Installing from requirements.txt..."
        python -m pip install -r requirements.txt
        
        # Platform-specific aiortc installation if needed
        if ! pip show aiortc >/dev/null 2>&1; then
            print_warning "aiortc not installed. Attempting platform-specific installation..."
            
            case "$OS" in
                "windows")
                    print_status "Installing aiortc for Windows..."
                    python -m pip install aiortc==1.8.0 || {
                        print_error "Failed to install aiortc on Windows"
                        print_error "Try installing Visual Studio Build Tools or use conda instead"
                        return 1
                    }
                    ;;
                "macos")
                    print_status "Installing aiortc for macOS..."
                    python -m pip install aiortc==1.8.0 || {
                        print_error "Failed to install aiortc on macOS"
                        print_error "Install dependencies: brew install ffmpeg pkg-config"
                        return 1
                    }
                    ;;
                "linux")
                    print_status "Installing aiortc for Linux..."
                    python -m pip install aiortc==1.8.0 || {
                        print_error "Failed to install aiortc on Linux"
                        print_error "Install system dependencies first:"
                        print_error "Ubuntu/Debian: sudo apt-get install ffmpeg libavformat-dev libavcodec-dev libavdevice-dev libavfilter-dev libavutil-dev libswscale-dev libswresample-dev pkg-config"
                        print_error "CentOS/RHEL: sudo yum install ffmpeg-devel pkgconfig"
                        return 1
                    }
                    ;;
            esac
        fi
    else
        # Conda environment - dependencies should already be installed via environment.yml
        print_status "Verifying conda environment dependencies..."
        
        # Check key packages
        local missing_packages=()
        
        if ! python -c "import aiortc" 2>/dev/null; then
            missing_packages+=("aiortc")
        fi
        
        if ! python -c "import boto3" 2>/dev/null; then
            missing_packages+=("boto3")
        fi
        
        if ! python -c "import websockets" 2>/dev/null; then
            missing_packages+=("websockets")
        fi
        
        if [ ${#missing_packages[@]} -gt 0 ]; then
            print_warning "Missing packages detected: ${missing_packages[*]}"
            print_status "Installing missing packages via pip..."
            
            for package in "${missing_packages[@]}"; do
                case "$package" in
                    "aiortc")
                        # Prefer conda for aiortc
                        conda install -c conda-forge aiortc -y || python -m pip install aiortc==1.8.0
                        ;;
                    *)
                        python -m pip install "$package"
                        ;;
                esac
            done
        fi
        
        # Install additional pip packages if requirements.txt exists
        if [ -f "requirements.txt" ]; then
            print_status "Installing additional packages from requirements.txt..."
            # Install packages that might not be in environment.yml
            python -m pip install -r requirements.txt --ignore-installed || {
                print_warning "Some packages from requirements.txt failed to install"
                print_status "This is normal for packages that may not be available"
            }
        fi
    fi
    
    # Verify critical dependencies
    print_status "Verifying installation..."
    python -c "
import sys
try:
    import aiortc
    import boto3
    import websockets
    print('✓ All critical dependencies verified')
except ImportError as e:
    print(f'✗ Missing dependency: {e}')
    sys.exit(1)
"
    
    print_success "Dependencies installed and verified successfully"
}

# Function to test environment setup
test_environment_setup() {
    print_status "Testing environment setup on $OS"
    print_status "=================================="
    
    # Test 1: Check conda availability
    print_status "Test 1: Conda availability"
    if command -v conda >/dev/null 2>&1; then
        CONDA_VERSION=$(conda --version | cut -d' ' -f2)
        print_success "Conda $CONDA_VERSION found"
    else
        print_error "Conda not found in PATH"
        return 1
    fi
    
    # Test 2: Check environment exists
    print_status "Test 2: Environment existence"
    if conda env list | grep -q "nova-s2s-webrtc"; then
        print_success "Environment 'nova-s2s-webrtc' exists"
    else
        print_error "Environment 'nova-s2s-webrtc' not found"
        print_status "Run the setup script first: ./start-python-server.sh"
        return 1
    fi
    
    # Test 3: Test environment activation
    print_status "Test 3: Environment activation"
    local original_env="$CONDA_DEFAULT_ENV"
    
    if activate_conda_environment "nova-s2s-webrtc"; then
        print_success "Environment activation successful"
        
        # Test 4: Check Python version
        print_status "Test 4: Python version"
        PYTHON_VERSION=$(python --version 2>&1 | cut -d' ' -f2)
        print_success "Python $PYTHON_VERSION"
        
        # Test 5: Check critical packages
        print_status "Test 5: Critical package imports"
        python -c "
import sys
packages = ['aiortc', 'boto3', 'websockets', 'cv2', 'PIL', 'numpy']
failed = []

for pkg in packages:
    try:
        __import__(pkg)
        print(f'✓ {pkg}')
    except ImportError:
        print(f'✗ {pkg}')
        failed.append(pkg)

if failed:
    print(f'Failed imports: {failed}')
    sys.exit(1)
else:
    print('All critical packages imported successfully')
"
        
        if [ $? -eq 0 ]; then
            print_success "All package imports successful"
        else
            print_error "Some package imports failed"
            return 1
        fi
        
        # Test 6: Check system dependencies
        print_status "Test 6: System dependencies"
        if command -v ffmpeg >/dev/null 2>&1; then
            FFMPEG_VERSION=$(ffmpeg -version 2>&1 | head -n1 | cut -d' ' -f3)
            print_success "ffmpeg $FFMPEG_VERSION found"
        else
            print_error "ffmpeg not found (may cause WebRTC issues)"
        fi
        
        # Restore original environment
        if [[ -n "$original_env" && "$original_env" != "nova-s2s-webrtc" ]]; then
            conda activate "$original_env" 2>/dev/null || conda deactivate 2>/dev/null || true
        else
            conda deactivate 2>/dev/null || true
        fi
    else
        print_error "Environment activation failed"
        return 1
    fi
    
    print_status "=================================="
    print_success "All tests passed! Environment is ready on $OS"
    print_status "You can now run: ./start-python-server.sh"
    
    return 0
}

# Function to check environment configuration
check_environment() {
    print_status "Checking environment configuration..."
    
    # Check if .env file exists
    if [ ! -f ".env" ]; then
        if [ -f ".env.template" ]; then
            print_warning "🔧 First-time setup: .env file not found"
            print_warning "📋 Please create your configuration file:"
            print_warning "   cp .env.template .env"
            print_warning "   # Then edit .env with your AWS credentials"
            print_warning ""
            print_warning "💡 Required: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY"
            print_warning "📖 See .env.template for all available options"
            return 1
        else
            print_warning ".env file not found, using environment variables and defaults"
        fi
    else
        print_status "Loading environment from .env file"
        set -a  # Export all variables
        source .env
        set +a  # Stop exporting
    fi
    
    # Check required AWS credentials
    if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
        print_warning "AWS credentials not found in environment"
        print_warning "Please set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY"
        print_warning "Or configure AWS CLI with 'aws configure'"
    fi
    
    # Set defaults for missing variables
    export AWS_REGION="${AWS_REGION:-$DEFAULT_REGION}"
    export KVS_CHANNEL_NAME="${KVS_CHANNEL_NAME:-$DEFAULT_CHANNEL}"
    export BEDROCK_MODEL_ID="${BEDROCK_MODEL_ID:-$DEFAULT_MODEL}"
    export SERVER_PORT="${SERVER_PORT:-$DEFAULT_PORT}"
    export LOGLEVEL="${LOGLEVEL:-INFO}"
    
    print_success "Environment configuration loaded"
}

# Function to create logs directory
setup_logging() {
    # Create logs directory if it doesn't exist
    mkdir -p "$LOGS_DIR"
    
    # Set log file path
    export LOG_FILE="${LOG_FILE:-$LOGS_DIR/webrtc_server.log}"
    
    print_status "Logs will be written to: $LOG_FILE"
}

# Function to check system dependencies with platform-specific guidance
check_system_dependencies() {
    print_status "Checking system dependencies for $OS..."
    
    local missing_deps=()
    
    # Check for ffmpeg (required for aiortc)
    if ! command_exists ffmpeg; then
        missing_deps+=("ffmpeg")
        print_warning "ffmpeg not found. Required for WebRTC audio/video processing"
        
        case "$OS" in
            "macos")
                print_warning "Install with: brew install ffmpeg"
                ;;
            "linux")
                print_warning "Install with: sudo apt-get install ffmpeg (Ubuntu/Debian)"
                print_warning "            or: sudo yum install ffmpeg (CentOS/RHEL)"
                print_warning "            or: sudo pacman -S ffmpeg (Arch Linux)"
                ;;
            "windows")
                print_warning "Install ffmpeg for Windows:"
                print_warning "  1. Download from: https://ffmpeg.org/download.html#build-windows"
                print_warning "  2. Add to PATH, or use: winget install Gyan.FFmpeg"
                print_warning "  3. Or use conda: conda install -c conda-forge ffmpeg"
                ;;
        esac
    else
        print_success "ffmpeg found: $(ffmpeg -version 2>&1 | head -n1 | cut -d' ' -f3)"
    fi
    
    # Check for pkg-config
    if ! command_exists pkg-config; then
        missing_deps+=("pkg-config")
        print_warning "pkg-config not found. May cause issues during compilation"
        
        case "$OS" in
            "macos")
                print_warning "Install with: brew install pkg-config"
                ;;
            "linux")
                print_warning "Install with: sudo apt-get install pkg-config (Ubuntu/Debian)"
                print_warning "            or: sudo yum install pkgconfig (CentOS/RHEL)"
                ;;
            "windows")
                print_warning "pkg-config for Windows:"
                print_warning "  Usually handled by conda, or install via MSYS2"
                print_warning "  conda install -c conda-forge pkg-config"
                ;;
        esac
    else
        print_success "pkg-config found"
    fi
    
    # Platform-specific additional checks
    case "$OS" in
        "windows")
            # Check for Visual Studio Build Tools (helpful for some packages)
            if ! command_exists cl 2>/dev/null && ! command_exists gcc 2>/dev/null; then
                print_warning "No C compiler found. Some packages may fail to install"
                print_warning "Consider installing Visual Studio Build Tools or use conda packages"
            fi
            ;;
        "linux")
            # Check for essential build tools
            if ! command_exists gcc; then
                print_warning "gcc not found. Install build-essential (Ubuntu) or Development Tools (CentOS)"
            fi
            ;;
    esac
    
    if [ ${#missing_deps[@]} -eq 0 ]; then
        print_success "All system dependencies are available"
    else
        print_warning "Missing dependencies: ${missing_deps[*]}"
        print_status "Note: Conda will handle most dependencies automatically"
    fi
    
    print_success "System dependency check completed for $OS"
}

# Function to start the server
start_server() {
    # Ensure we're in the correct directory
    cd "$PYTHON_SERVER_DIR"
    
    print_status "Starting Nova S2S WebRTC Python Server..."
    print_status "Configuration:"
    print_status "  Region: $AWS_REGION"
    print_status "  Channel: $KVS_CHANNEL_NAME"
    print_status "  Model: $BEDROCK_MODEL_ID"
    print_status "  Port: $SERVER_PORT"
    print_status "  Log Level: $LOGLEVEL"
    print_status "  Log File: $LOG_FILE"
    
    # Verify webrtc_server.py exists
    if [ ! -f "webrtc_server.py" ]; then
        print_error "webrtc_server.py not found in $PYTHON_SERVER_DIR"
        print_error "Current directory: $(pwd)"
        print_error "Available Python files:"
        ls -la *.py 2>/dev/null || print_error "No Python files found"
        return 1
    fi
    
    # Build command line arguments
    ARGS="--region $AWS_REGION --channel-name $KVS_CHANNEL_NAME --model-id $BEDROCK_MODEL_ID"
    

    
    print_success "Server starting with command: python webrtc_server.py $ARGS"
    print_status "Press Ctrl+C to stop the server"
    print_status "----------------------------------------"
    
    # Start the server
    exec python webrtc_server.py $ARGS
}

# Function to display usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "🚀 WebRTC Server Startup Script"
    echo ""
    echo "Options:"
    echo "  --help, -h          Show this help message"
    echo "  --test-only         Test environment setup without starting server"
    echo "  --skip-deps         Skip dependency installation"
    echo "  --fallback-venv     Use Python venv instead of conda (not recommended)"
    echo "  --region REGION     Set AWS region (default: $DEFAULT_REGION)"
    echo "  --channel CHANNEL   Set KVS channel name (default: $DEFAULT_CHANNEL)"
    echo "  --model MODEL       Set Bedrock model ID (default: $DEFAULT_MODEL)"
    echo ""
    echo "Environment Variables:"
    echo "  AWS_REGION          AWS region"
    echo "  AWS_ACCESS_KEY_ID   AWS access key"
    echo "  AWS_SECRET_ACCESS_KEY AWS secret key"
    echo "  KVS_CHANNEL_NAME    KVS WebRTC channel name"
    echo "  BEDROCK_MODEL_ID    Bedrock model identifier"
    echo "  LOGLEVEL           Logging level (DEBUG, INFO, WARNING, ERROR)"
    echo ""
    echo "Examples:"
    echo "  $0                  Start server with conda (default)"
    echo "  $0 --test-only      Test environment setup only"
    echo "  $0 --fallback-venv  Start server with Python venv (fallback)"
    echo ""
    echo "Cross-Platform Support:"
    echo "  Supported Platforms: macOS, Linux, Windows (Git Bash/WSL)"
    echo "  Default: Uses conda for maximum cross-platform compatibility"
    echo "  Conda Benefits:"
    echo "    - Unified package management across all platforms"
    echo "    - Automatic handling of system dependencies (ffmpeg, etc.)"
    echo "    - Pre-compiled binaries for aiortc and complex packages"
    echo "    - Better reproducibility and easier deployment"
    echo "    - Eliminates most compilation issues on Windows"
    echo ""
    echo "Platform-Specific Notes:"
    echo "  macOS: Requires Xcode Command Line Tools for some packages"
    echo "  Linux: Most distributions supported, prefers conda-forge packages"
    echo "  Windows: Works with Git Bash, PowerShell, or WSL"
    echo ""
}

# Function to handle cleanup on exit
cleanup() {
    print_status "Shutting down server..."
    # Kill any background processes if needed
    exit 0
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

# Parse command line arguments
SKIP_DEPS=false
USE_VENV_FALLBACK=false
TEST_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            usage
            exit 0
            ;;
        --test-only)
            TEST_ONLY=true
            shift
            ;;
        --skip-deps)
            SKIP_DEPS=true
            shift
            ;;
        --fallback-venv)
            USE_VENV_FALLBACK=true
            shift
            ;;
        --region)
            export AWS_REGION="$2"
            shift 2
            ;;
        --channel)
            export KVS_CHANNEL_NAME="$2"
            shift 2
            ;;
        --model)
            export BEDROCK_MODEL_ID="$2"
            shift 2
            ;;
        *)
            print_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Main execution
main() {
    print_status "Nova S2S WebRTC Python Server Startup"
    print_status "======================================"
    
    # Check system dependencies (informational only for conda)
    if [ "$USE_VENV_FALLBACK" = true ]; then
        check_system_dependencies
    fi
    
    # Setup environment and dependencies
    if [ "$SKIP_DEPS" = false ]; then
        if [ "$USE_VENV_FALLBACK" = true ]; then
            print_warning "Using Python venv fallback (not recommended for production)"
            if ! check_python_version; then
                exit 1
            fi
            setup_virtual_environment
            install_dependencies
        else
            # Default: Use conda
            if ! check_conda_installation; then
                exit 1
            fi
            setup_conda_environment
            install_dependencies
        fi
    else
        print_status "Skipping dependency installation"
        cd "$PYTHON_SERVER_DIR"
        if [ "$USE_VENV_FALLBACK" = true ]; then
            if [ -d ".venv" ]; then
                source .venv/bin/activate
            else
                print_error "Virtual environment not found. Run without --skip-deps first."
                exit 1
            fi
        else
            # Default: Use conda
            if ! check_conda_installation; then
                exit 1
            fi
            activate_conda_environment "nova-s2s-webrtc"
        fi
    fi
    
    # If test-only mode, run tests and exit (skip environment config check)
    if [ "$TEST_ONLY" = true ]; then
        test_environment_setup
        exit $?
    fi
    
    # Check environment configuration
    check_environment
    
    # Setup logging
    setup_logging
    
    # Start the server
    start_server
}

# Run main function
main "$@"