#!/bin/bash

# Nova S2S WebRTC React Client Startup Script
# This script sets up the environment and starts the React WebRTC client

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory and project paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
REACT_CLIENT_DIR="$PROJECT_ROOT/react-webrtc-client"

# Default configuration
DEFAULT_PORT=3000
DEFAULT_REGION="ap-northeast-1"
DEFAULT_CHANNEL="nova-s2s-webrtc-test"

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

# Function to check Node.js version
check_node_version() {
    if ! command_exists node; then
        print_error "Node.js is not installed or not in PATH"
        print_error "Please install Node.js 16.x or higher from https://nodejs.org/"
        return 1
    fi
    
    # Check Node.js version (requires 16+)
    NODE_VERSION=$(node -v | sed 's/v//')
    REQUIRED_VERSION="16.0.0"
    
    if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$NODE_VERSION" | sort -V | head -n1)" = "$REQUIRED_VERSION" ]; then
        print_success "Node.js $NODE_VERSION detected"
        return 0
    else
        print_error "Node.js $NODE_VERSION detected, but Node.js $REQUIRED_VERSION or higher is required"
        return 1
    fi
}

# Function to check npm version
check_npm_version() {
    if ! command_exists npm; then
        print_error "npm is not installed or not in PATH"
        print_error "npm should be installed with Node.js"
        return 1
    fi
    
    NPM_VERSION=$(npm -v)
    print_success "npm $NPM_VERSION detected"
    return 0
}

# Function to install dependencies
install_dependencies() {
    print_status "Checking and installing Node.js dependencies..."
    
    cd "$REACT_CLIENT_DIR"
    
    # Check if package.json exists
    if [ ! -f "package.json" ]; then
        print_error "package.json not found in $REACT_CLIENT_DIR"
        return 1
    fi
    
    # Check if node_modules exists and is up to date
    if [ ! -d "node_modules" ] || [ "package.json" -nt "node_modules" ]; then
        print_status "Installing dependencies with npm..."
        
        # Clear npm cache if there are issues
        if [ -d "node_modules" ]; then
            print_status "Cleaning existing node_modules..."
            rm -rf node_modules package-lock.json
        fi
        
        # Install dependencies
        npm install
        
        if [ $? -eq 0 ]; then
            print_success "Dependencies installed successfully"
        else
            print_error "Failed to install dependencies"
            print_error "Try running: npm cache clean --force && npm install"
            return 1
        fi
    else
        print_status "Dependencies are up to date"
    fi
}

# Function to check environment configuration
check_environment() {
    print_status "Checking environment configuration..."
    
    cd "$REACT_CLIENT_DIR"
    
    # Check if .env file exists
    if [ ! -f ".env" ]; then
        if [ -f ".env.template" ]; then
            print_warning ".env file not found. Please copy .env.template to .env and configure it:"
            print_warning "cp .env.template .env"
            print_warning "Then edit .env with your AWS credentials and configuration"
            
            # Offer to create a basic .env file
            read -p "Would you like to create a basic .env file now? (y/n): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                create_basic_env_file
            else
                return 1
            fi
        else
            print_warning ".env file not found, using environment variables and defaults"
        fi
    else
        print_status "Loading environment from .env file"
    fi
    
    # Set defaults for missing variables
    export PORT="${PORT:-$DEFAULT_PORT}"
    # Don't set HOST as it causes webpack dev server issues
    # Let webpack dev server use its default (0.0.0.0)
    if [ -n "$HOST" ]; then
        print_warning "HOST environment variable detected ($HOST), will be unset to avoid webpack dev server issues"
    fi
    export REACT_APP_AWS_REGION="${REACT_APP_AWS_REGION:-$DEFAULT_REGION}"
    export REACT_APP_KVS_CHANNEL_NAME="${REACT_APP_KVS_CHANNEL_NAME:-$DEFAULT_CHANNEL}"
    export GENERATE_SOURCEMAP="${GENERATE_SOURCEMAP:-false}"
    
    # Check required AWS credentials
    if [ -z "$REACT_APP_AWS_ACCESS_KEY_ID" ] || [ -z "$REACT_APP_AWS_SECRET_ACCESS_KEY" ]; then
        print_warning "AWS credentials not found in .env file"
        print_warning "Please set REACT_APP_AWS_ACCESS_KEY_ID and REACT_APP_AWS_SECRET_ACCESS_KEY in .env"
        print_warning "Note: These will be embedded in the client-side code"
    fi
    
    print_success "Environment configuration loaded"
}

# Function to create a basic .env file
create_basic_env_file() {
    print_status "Creating basic .env file..."
    
    cat > .env << EOF
# Nova S2S WebRTC Client Configuration
# Generated by start-react-client.sh

# Build Configuration
GENERATE_SOURCEMAP=false

# AWS Configuration
REACT_APP_AWS_REGION=$DEFAULT_REGION
REACT_APP_AWS_ACCESS_KEY_ID=your_access_key_here
REACT_APP_AWS_SECRET_ACCESS_KEY=your_secret_key_here
REACT_APP_AWS_SESSION_TOKEN=your_session_token_here

# KVS WebRTC Configuration
REACT_APP_KVS_CHANNEL_NAME=$DEFAULT_CHANNEL

# Development Server Configuration
PORT=$DEFAULT_PORT
# HOST is not set to avoid webpack dev server issues
EOF
    
    print_success "Basic .env file created"
    print_warning "Please edit .env and update the AWS credentials before starting the client"
}

# Function to build the application
build_application() {
    if [ "$BUILD_MODE" = "true" ]; then
        print_status "Building React application for production..."
        
        npm run build
        
        if [ $? -eq 0 ]; then
            print_success "Application built successfully"
            print_status "Build files are in the 'build' directory"
            print_status "You can serve them with a static file server"
            return 0
        else
            print_error "Build failed"
            return 1
        fi
    fi
}

# Function to start the development server
start_dev_server() {
    print_status "Starting Nova S2S WebRTC React Client..."
    print_status "Configuration:"
    print_status "  Host: ${HOST:-0.0.0.0 (default)}"
    print_status "  Port: $PORT"
    print_status "  AWS Region: $REACT_APP_AWS_REGION"
    print_status "  KVS Channel: $REACT_APP_KVS_CHANNEL_NAME"
    print_status "  Source Maps: $GENERATE_SOURCEMAP"
    
    print_success "Starting development server..."
    print_status "The application will open in your default browser"
    print_status "Press Ctrl+C to stop the server"
    print_status "----------------------------------------"
    
    # Use env to explicitly control environment variables and exclude HOST
    # This ensures HOST is not passed to npm start, avoiding webpack dev server issues
    print_status "Starting with clean HOST environment..."
    
    # Start the development server with explicit environment control
    exec env -u HOST npm start
}

# Function to serve built application
serve_built_app() {
    if [ ! -d "build" ]; then
        print_error "Build directory not found. Please run with --build first"
        return 1
    fi
    
    print_status "Serving built application..."
    
    # Check if serve is installed globally
    if command_exists serve; then
        print_status "Using 'serve' to host the application on port $PORT"
        exec serve -s build -l $PORT
    else
        print_warning "'serve' not found. Installing locally..."
        npx serve -s build -l $PORT
    fi
}

# Function to display usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --help, -h          Show this help message"
    echo "  --skip-deps         Skip dependency installation"
    echo "  --build             Build for production instead of starting dev server"
    echo "  --serve             Serve built application (requires --build first)"
    echo "  --port PORT         Set development server port (default: $DEFAULT_PORT)"
    echo "  --host HOST         Set development server host (default: 0.0.0.0)"
    echo "  --region REGION     Set AWS region (default: ap-northeast-1)"
    echo "  --channel CHANNEL   Set KVS channel name (default: $DEFAULT_CHANNEL)"
    echo ""
    echo "Environment Variables:"
    echo "  PORT                Development server port"
    echo "  HOST                Development server host"
    echo "  REACT_APP_AWS_REGION          AWS region"
    echo "  REACT_APP_AWS_ACCESS_KEY_ID   AWS access key (embedded in client)"
    echo "  REACT_APP_AWS_SECRET_ACCESS_KEY AWS secret key (embedded in client)"
    echo "  REACT_APP_KVS_CHANNEL_NAME    KVS WebRTC channel name"
    echo "  GENERATE_SOURCEMAP            Generate source maps (true/false)"
    echo ""
    echo "Examples:"
    echo "  $0                  Start development server"
    echo "  $0 --build          Build for production"
    echo "  $0 --serve          Serve built application"
    echo "  $0 --port 3001      Start on port 3001"
    echo ""
}

# Function to handle cleanup on exit
cleanup() {
    print_status "Shutting down client..."
    # Kill any background processes if needed
    exit 0
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

# Parse command line arguments
SKIP_DEPS=false
BUILD_MODE=false
SERVE_MODE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            usage
            exit 0
            ;;
        --skip-deps)
            SKIP_DEPS=true
            shift
            ;;
        --build)
            BUILD_MODE=true
            shift
            ;;
        --serve)
            SERVE_MODE=true
            shift
            ;;
        --port)
            export PORT="$2"
            shift 2
            ;;
        --host)
            if [ "$2" = "localhost" ]; then
                print_warning "HOST=localhost can cause webpack dev server issues, using default instead"
            else
                export HOST="$2"
            fi
            shift 2
            ;;
        --region)
            export REACT_APP_AWS_REGION="$2"
            shift 2
            ;;
        --channel)
            export REACT_APP_KVS_CHANNEL_NAME="$2"
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
    print_status "Nova S2S WebRTC React Client Startup"
    print_status "====================================="
    
    # Check Node.js and npm installation
    if ! check_node_version; then
        exit 1
    fi
    
    if ! check_npm_version; then
        exit 1
    fi
    
    # Install dependencies if not skipped
    if [ "$SKIP_DEPS" = false ]; then
        install_dependencies
    else
        print_status "Skipping dependency installation"
        cd "$REACT_CLIENT_DIR"
    fi
    
    # Check environment configuration
    check_environment
    
    # Handle different modes
    if [ "$BUILD_MODE" = "true" ]; then
        build_application
    elif [ "$SERVE_MODE" = "true" ]; then
        serve_built_app
    else
        start_dev_server
    fi
}

# Run main function
main "$@"