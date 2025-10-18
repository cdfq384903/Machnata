#!/usr/bin/env bash
set -e

echo "📦 Installing base dependencies..."
sudo apt update -y
sudo apt install -y build-essential cmake git curl wget python3 python3-pip protobuf-compiler

echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

echo "📦 Installing C / C++ dependencies..."
sudo apt install -y libprotobuf-dev protobuf-c-compiler libprotobuf-c-dev libcjson-dev

echo "📦 Installing Go dependencies..."
sudo apt install -y golang-go golang-goprotobuf-dev

echo "✅ All dependencies installed successfully!"
echo "You can now run:"
echo "    python3 src/schema_generator.py --all --langs cpp"
