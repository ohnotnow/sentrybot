# syntax=docker/dockerfile:1

# Use the official node image as the base image
FROM node:20-slim
# Install Python and curl
RUN apt-get update && apt-get install -y curl
# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
# Ensure uv is in the PATH
ENV PATH="/root/.local/bin:$PATH"

# Set the working directory to /app
WORKDIR /app

# Copy the requirements file into the container
COPY .python-version pyproject.toml uv.lock ./

RUN uv sync

# Copy the rest of the application code into the container
COPY . .

# Run the main.py script
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "main.py"]
