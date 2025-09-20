# Use an official lightweight Python image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file first to leverage Docker's layer caching
COPY requirements.txt .

# Install the Python dependencies (add flask if your health.py needs it)
RUN pip install --no-cache-dir -r requirements.txt

# Copy all your project files into the container
COPY . .

# Make the startup script executable
RUN chmod +x ./start.sh

# Expose the port your health check server will run on (e.g., 8080)
EXPOSE 8080

# Optional: Update health check to use the new health.py server
# Note: Koyeb ignores this for Worker services.
HEALTHCHECK --interval=60s --timeout=10s --start-period=15s --retries=3 \
  CMD curl --fail http://localhost:8080/ || exit 1

# Command to run the startup script when the container starts
CMD ["./start.sh"]

