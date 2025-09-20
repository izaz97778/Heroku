#!/bin/bash

# Start the health check web server in the background
echo "Starting health check server..."
python health.py &

# Start the main Telegram bot application in the foreground
echo "Starting Telegram bot..."
python heroku_bot.py
