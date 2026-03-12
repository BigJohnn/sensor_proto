# syntax=docker/dockerfile:1.7
FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG INSTALL_REALSENSE=1
ARG INSTALL_ORBBEC=1
ARG PYORBBECSDK_REPO=git@github.com:orbbec/pyorbbecsdk.git

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    python3-venv \
    build-essential \
    cmake \
    pkg-config \
    git \
    openssh-client \
    libusb-1.0-0-dev \
    libgl1 \
    libegl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    usbutils \
    udev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY pyproject.toml ./
COPY src ./src
COPY tests ./tests
COPY configs ./configs

RUN python3 -m pip install --upgrade pip setuptools wheel pytest && \
    python3 -m pip install numpy opencv-python-headless && \
    python3 -m pip install -e .

RUN if [ "${INSTALL_REALSENSE}" = "1" ]; then \
      python3 -m pip install pyrealsense2; \
    fi

RUN --mount=type=ssh if [ "${INSTALL_ORBBEC}" = "1" ]; then \
      git clone --depth 1 "${PYORBBECSDK_REPO}" /tmp/pyorbbecsdk && \
      python3 -m pip install pybind11 wheel setuptools && \
      mkdir -p /tmp/pyorbbecsdk/build && \
      cd /tmp/pyorbbecsdk/build && \
      cmake .. -Dpybind11_DIR="$(python3 -m pybind11 --cmakedir)" && \
      cmake --build . -j"$(nproc)" && \
      cmake --install . && \
      cd /tmp/pyorbbecsdk && \
      python3 -m pip install . && \
      rm -rf /tmp/pyorbbecsdk; \
    fi

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python3", "-m", "sensor_proto.main"]
CMD ["--config", "configs/mock-session.json"]
