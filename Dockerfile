FROM python:3.10-slim

# Disable python cache
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && \
    apt-get install -y \
        ffmpeg \
        gcc \
        libffi-dev \
        wget \
        unzip \
        libvulkan1 \
        libgomp1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Real-ESRGAN (for image upscaling)
RUN wget -q https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-ubuntu.zip \
    && unzip -q realesrgan-ncnn-vulkan-20220424-ubuntu.zip \
    && chmod +x realesrgan-ncnn-vulkan \
    && mv realesrgan-ncnn-vulkan /usr/local/bin/ \
    && mv models/ /usr/local/bin/models/ \
    && rm realesrgan-ncnn-vulkan-20220424-ubuntu.zip \
    && rm -rf __MACOSX

# Set working directory
WORKDIR /app

# Copy requirements first (docker caching)
COPY requirements.txt .

# Install python dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Run bot
CMD ["python3", "bot.py"]
