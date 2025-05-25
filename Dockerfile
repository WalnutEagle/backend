# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the dependencies file to the working directory
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# --no-cache-dir reduces image size
# --trusted-host pypi.python.org helps with potential network issues in some environments
RUN pip install --no-cache-dir --trusted-host pypi.python.org --trusted-host files.pythonhosted.org --trusted-host pypi.org -r requirements.txt

# Copy the content of the local src directory to the working directory
COPY ./app /app/app

# Make port 8080 available to the world outside this container
EXPOSE 8080

# Define environment variable (optional, can be set in OpenShift)
# ENV MODULE_NAME="app.main"
# ENV VARIABLE_NAME="app"

# Run app.main:app when the container launches
# Uvicorn is a lightning-fast ASGI server.
# --host 0.0.0.0 makes it accessible from outside the container.
# OpenShift will manage the external port mapping.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]