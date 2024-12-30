# Use the official Python image from the Docker Hub
FROM python:3.10-alpine

# Set the working directory in the container
WORKDIR /app

RUN pip install --no-cache-dir gunicorn

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY import.py .

COPY web/ .

COPY spot_server.py .

# Expose port 5000 for the Flask app
EXPOSE 5000

# Define environment variable
ENV FLASK_APP=spot_server.py
ENV SPOT_NO_API=1

# Run the Gunicorn server
CMD ["gunicorn", "-b", "0.0.0.0:5000", "spot_server:app"]