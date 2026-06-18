"""
Shared configuration constants for MT5 Autonomous AutoTrader.
Centralizes magic numbers, API URLs, and credentials.
"""
import os
import platform
import multiprocessing
import subprocess
import logging
import psutil

logger = logging.getLogger(__name__)

# ==========================================
# GPU AUTO-DETECTION
# ==========================================
def detect_gpu():
    """Detect GPU: name, vendor, VRAM, cores, compute capability, driver."""
    gpu_list = []
    gpu_info = {
        "gpu_count": 0,
        "gpu_names": [],
        "gpu_vram_total_mb": 0,
        "gpu_vram_total_gb": 0.0,
        "gpu_cores": 0,
        "gpu_compute_capability": "0.0",
        "gpu_driver_version": "N/A",
        "gpu_vendor": "None",
        "gpu_name": "None",
        "gpu_has_cuda": False,
        "gpu_has_opencl": False,
        "gpu_pci_bus": "N/A",
        "gpu_pci_slot": "N/A",
        "gpu_clock_mhz": 0,
        "gpu_memory_clock_mhz": 0,
        "gpu_power_draw_w": 0,
        "gpu_temp_c": 0,
        "gpu_utilization_pct": 0,
    }

    system = platform.system()

    # --- NVIDIA GPU (nvidia-smi) ---
    if system == "Windows":
        try:
            output = subprocess.check_output(
                ['nvidia-smi', '--query-gpu=gpu_name,driver_version,memory.total,memory.used,memory.free,'
                 'utilization.gpu,clocks.current.graphics,clocks.current.memory,temperature.gpu,'
                 'power.draw,pci.bus_id,compute_cap',
                 '--format=csv,noheader,nounits'],
                stderr=subprocess.DEVNULL, timeout=5
            ).decode().strip()
            if output:
                for line in output.splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 11:
                        gpu_list.append({
                            "name": parts[0],
                            "driver": parts[1],
                            "vram_total_mb": int(float(parts[2])),
                            "vram_used_mb": int(float(parts[3])),
                            "vram_free_mb": int(float(parts[4])),
                            "utilization_pct": int(float(parts[5])),
                            "clock_graphics_mhz": int(float(parts[6])),
                            "clock_memory_mhz": int(float(parts[7])),
                            "temp_c": int(float(parts[8])),
                            "power_draw_w": int(float(parts[9])) if parts[9] not in ("[N/A]", "N/A") else 0,
                            "pci_bus_id": parts[10] if len(parts) > 10 else "N/A",
                            "compute_cap": parts[11] if len(parts) > 11 else "0.0",
                        })
        except Exception as e:
            logger.debug("nvidia-smi GPU detection failed: %s", e)
    if not gpu_list and system == "Windows":
        try:
            output = subprocess.check_output(
                'wmic path win32_videocontroller get Name,AdapterRAM,DriverVersion,'
                'VideoProcessor,CurrentHorizontalResolution,CurrentVerticalResolution /value',
                shell=True, stderr=subprocess.DEVNULL, timeout=5
            ).decode()
            current_gpu = {}
            for line in output.splitlines():
                line = line.strip()
                if "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip()
                    if key == "Name" and val:
                        current_gpu["name"] = val
                    elif key == "AdapterRAM":
                        try:
                            current_gpu["vram_total_mb"] = int(int(val) / (1024 * 1024))
                        except (ValueError, TypeError):
                            current_gpu["vram_total_mb"] = 0
                    elif key == "DriverVersion" and val:
                        current_gpu["driver"] = val
                    elif key == "VideoProcessor" and val:
                        current_gpu["video_processor"] = val
                elif current_gpu and "name" in current_gpu:
                    gpu_list.append({
                        "name": current_gpu["name"],
                        "driver": current_gpu.get("driver", "N/A"),
                        "vram_total_mb": current_gpu.get("vram_total_mb", 0),
                        "vram_used_mb": 0,
                        "vram_free_mb": current_gpu.get("vram_total_mb", 0),
                        "utilization_pct": 0,
                        "clock_graphics_mhz": 0,
                        "clock_memory_mhz": 0,
                        "temp_c": 0,
                        "power_draw_w": 0,
                        "pci_bus_id": "N/A",
                        "compute_cap": "0.0",
                        "video_processor": current_gpu.get("video_processor", "N/A"),
                    })
                    current_gpu = {}
            if current_gpu and "name" in current_gpu:
                gpu_list.append({
                    "name": current_gpu["name"],
                    "driver": current_gpu.get("driver", "N/A"),
                    "vram_total_mb": current_gpu.get("vram_total_mb", 0),
                    "vram_used_mb": 0,
                    "vram_free_mb": current_gpu.get("vram_total_mb", 0),
                    "utilization_pct": 0,
                    "clock_graphics_mhz": 0,
                    "clock_memory_mhz": 0,
                    "temp_c": 0,
                    "power_draw_w": 0,
                    "pci_bus_id": "N/A",
                    "compute_cap": "0.0",
                    "video_processor": current_gpu.get("video_processor", "N/A"),
                })
        except Exception as e:
            logger.debug("WMI GPU fallback failed: %s", e)

    # --- Linux GPU detection via /sys ---
    if not gpu_list and system == "Linux":
        try:
            vendor_ids = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel"}
            for pci_dir in os.listdir("/sys/bus/pci/devices/"):
                vendor_path = f"/sys/bus/pci/devices/{pci_dir}/vendor"
                class_path = f"/sys/bus/pci/devices/{pci_dir}/class"
                if os.path.exists(class_path):
                    with open(class_path) as f:
                        pci_class = f.read().strip()
                    if pci_class.startswith("0x0300"):  # VGA controller
                        vendor_id = "unknown"
                        if os.path.exists(vendor_path):
                            with open(vendor_path) as f:
                                vendor_id = f.read().strip()
                        vendor_name = vendor_ids.get(vendor_id, "Unknown")
                        name_path = f"/sys/bus/pci/devices/{pci_dir}/product"
                        name = "Unknown"
                        if os.path.exists(name_path):
                            with open(name_path) as f:
                                name = f.read().strip()
                        gpu_list.append({
                            "name": f"{vendor_name} {name}",
                            "driver": "N/A",
                            "vram_total_mb": 0,
                            "vram_used_mb": 0,
                            "vram_free_mb": 0,
                            "utilization_pct": 0,
                            "clock_graphics_mhz": 0,
                            "clock_memory_mhz": 0,
                            "temp_c": 0,
                            "power_draw_w": 0,
                            "pci_bus_id": pci_dir,
                            "compute_cap": "0.0",
                        })
        except Exception as e:
            logger.debug("Linux GPU detection failed: %s", e)

    # --- Populate GPU summary from detected GPUs ---
    if gpu_list:
        gpu_info["gpu_count"] = len(gpu_list)
        gpu_info["gpu_names"] = [g["name"] for g in gpu_list]
        gpu_info["gpu_name"] = gpu_list[0]["name"]
        gpu_info["gpu_driver_version"] = gpu_list[0].get("driver", "N/A")
        gpu_info["gpu_vram_total_mb"] = sum(g.get("vram_total_mb", 0) for g in gpu_list)
        gpu_info["gpu_vram_total_gb"] = round(gpu_info["gpu_vram_total_mb"] / 1024, 1)
        gpu_info["gpu_driver_version"] = gpu_list[0].get("driver", "N/A")
        gpu_info["gpu_pci_bus"] = gpu_list[0].get("pci_bus_id", "N/A")
        gpu_info["gpu_clock_mhz"] = gpu_list[0].get("clock_graphics_mhz", 0)
        gpu_info["gpu_memory_clock_mhz"] = gpu_list[0].get("clock_memory_mhz", 0)
        gpu_info["gpu_power_draw_w"] = gpu_list[0].get("power_draw_w", 0)
        gpu_info["gpu_temp_c"] = gpu_list[0].get("temp_c", 0)
        gpu_info["gpu_utilization_pct"] = gpu_list[0].get("utilization_pct", 0)
        gpu_info["gpu_compute_capability"] = gpu_list[0].get("compute_cap", "0.0")

        # Detect vendor
        name_lower = gpu_info["gpu_name"].lower()
        if "nvidia" in name_lower or "geforce" in name_lower or "quadro" in name_lower or "tesla" in name_lower:
            gpu_info["gpu_vendor"] = "NVIDIA"
            gpu_info["gpu_has_cuda"] = True
        elif "amd" in name_lower or "radeon" in name_lower or "navi" in name_lower:
            gpu_info["gpu_vendor"] = "AMD"
            gpu_info["gpu_has_opencl"] = True
        elif "intel" in name_lower or "iris" in name_lower or "uhd" in name_lower or "hd graphics" in name_lower:
            gpu_info["gpu_vendor"] = "Intel"
        else:
            gpu_info["gpu_vendor"] = "Unknown"

        # Estimate CUDA cores from name for NVIDIA
        if gpu_info["gpu_has_cuda"]:
            name = name_lower
            if "rtx 4090" in name: gpu_info["gpu_cores"] = 16384
            elif "rtx 4080" in name: gpu_info["gpu_cores"] = 9728
            elif "rtx 4070 ti" in name: gpu_info["gpu_cores"] = 7680
            elif "rtx 4070" in name: gpu_info["gpu_cores"] = 5888
            elif "rtx 4060" in name: gpu_info["gpu_cores"] = 3072
            elif "rtx 3090" in name: gpu_info["gpu_cores"] = 10496
            elif "rtx 3080" in name: gpu_info["gpu_cores"] = 8704
            elif "rtx 3070" in name: gpu_info["gpu_cores"] = 5888
            elif "rtx 3060" in name: gpu_info["gpu_cores"] = 3584
            elif "rtx 2080" in name: gpu_info["gpu_cores"] = 2944
            elif "rtx 2070" in name: gpu_info["gpu_cores"] = 2304
            elif "rtx 2060" in name: gpu_info["gpu_cores"] = 1920
            elif "gtx 1660" in name: gpu_info["gpu_cores"] = 1408
            elif "gtx 1080" in name: gpu_info["gpu_cores"] = 2560
            elif "gtx 1070" in name: gpu_info["gpu_cores"] = 1920
            elif "gtx 1060" in name: gpu_info["gpu_cores"] = 1280
            else: gpu_info["gpu_cores"] = 0
    else:
        gpu_info["gpu_vendor"] = "None"
        gpu_info["gpu_name"] = "Integrated / Not Detected"

    return gpu_info


# ==========================================
# SYSTEM AUTO-DETECTION
# ==========================================
def detect_system():
    """Comprehensive system detection: CPU, RAM, GPU, cores, threads, cache, architecture."""
    info = {}

    # --- CPU Core Counts ---
    try:
        info["logical_cores"] = multiprocessing.cpu_count()
    except Exception:
        info["logical_cores"] = 4
    try:
        info["physical_cores"] = psutil.cpu_count(logical=False) or info["logical_cores"]
    except Exception:
        info["physical_cores"] = info["logical_cores"]
    try:
        info["available_cores"] = psutil.cpu_count(logical=True) or info["logical_cores"]
    except Exception:
        info["available_cores"] = info["logical_cores"]

    # --- CPU Frequency ---
    try:
        freq = psutil.cpu_freq()
        if freq:
            info["cpu_freq_current_mhz"] = round(freq.current, 1)
            info["cpu_freq_min_mhz"] = round(freq.min, 1) if freq.min else 0
            info["cpu_freq_max_mhz"] = round(freq.max, 1) if freq.max else 0
        else:
            info["cpu_freq_current_mhz"] = 3000
            info["cpu_freq_min_mhz"] = 0
            info["cpu_freq_max_mhz"] = 0
    except Exception:
        info["cpu_freq_current_mhz"] = 3000
        info["cpu_freq_min_mhz"] = 0
        info["cpu_freq_max_mhz"] = 0

    # --- CPU Name ---
    try:
        if platform.system() == "Windows":
            output = subprocess.check_output(
                'wmic cpu get Name /value', shell=True, stderr=subprocess.DEVNULL
            ).decode()
            for line in output.splitlines():
                if line.startswith("Name="):
                    info["cpu_name"] = line.split("=", 1)[1].strip()
                    break
            else:
                info["cpu_name"] = "Unknown"
        elif platform.system() == "Linux":
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        info["cpu_name"] = line.split(":")[1].strip()
                        break
                else:
                    info["cpu_name"] = "Unknown"
        elif platform.system() == "Darwin":
            output = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], stderr=subprocess.DEVNULL
            ).decode().strip()
            info["cpu_name"] = output if output else "Unknown"
        else:
            info["cpu_name"] = "Unknown"
    except Exception:
        info["cpu_name"] = "Unknown"

    # --- CPU Architecture ---
    try:
        info["arch"] = platform.machine()
        info["arch_bits"] = platform.architecture()[0]
    except Exception:
        info["arch"] = "unknown"
        info["arch_bits"] = "unknown"

    # --- CPU Usage ---
    try:
        info["cpu_usage_percent"] = psutil.cpu_percent(interval=0.5)
    except Exception:
        info["cpu_usage_percent"] = 0.0

    # --- Memory ---
    try:
        mem = psutil.virtual_memory()
        info["ram_total_gb"] = round(mem.total / (1024**3), 1)
        info["ram_available_gb"] = round(mem.available / (1024**3), 1)
        info["ram_used_gb"] = round(mem.used / (1024**3), 1)
        info["ram_usage_percent"] = round(mem.percent, 1)
    except Exception:
        info["ram_total_gb"] = 16.0
        info["ram_available_gb"] = 12.0
        info["ram_used_gb"] = 4.0
        info["ram_usage_percent"] = 25.0

    # --- Swap ---
    try:
        swap = psutil.swap_memory()
        info["swap_total_gb"] = round(swap.total / (1024**3), 1) if swap.total else 0.0
        info["swap_used_gb"] = round(swap.used / (1024**3), 1) if swap.used else 0.0
    except Exception:
        info["swap_total_gb"] = 0.0
        info["swap_used_gb"] = 0.0

    # --- Disk ---
    try:
        disk = psutil.disk_usage("/")
        info["disk_total_gb"] = round(disk.total / (1024**3), 1)
        info["disk_free_gb"] = round(disk.free / (1024**3), 1)
        info["disk_usage_percent"] = round(disk.percent, 1)
    except Exception:
        try:
            disk = psutil.disk_usage("C:\\")
            info["disk_total_gb"] = round(disk.total / (1024**3), 1)
            info["disk_free_gb"] = round(disk.free / (1024**3), 1)
            info["disk_usage_percent"] = round(disk.percent, 1)
        except Exception:
            info["disk_total_gb"] = 0.0
            info["disk_free_gb"] = 0.0
            info["disk_usage_percent"] = 0.0

    # --- GPU Detection ---
    gpu = detect_gpu()
    info.update(gpu)

    # --- System Info ---
    try:
        info["platform"] = platform.system()
        info["platform_release"] = platform.release()
        info["platform_version"] = platform.version()
        info["hostname"] = platform.node()
        info["python_version"] = platform.python_version()
    except Exception:
        info["platform"] = "unknown"
        info["hostname"] = "unknown"
        info["python_version"] = "unknown"

    # --- Network ---
    try:
        net = psutil.net_io_counters()
        info["net_sent_gb"] = round(net.bytes_sent / (1024**3), 2)
        info["net_recv_gb"] = round(net.bytes_recv / (1024**3), 2)
    except Exception:
        info["net_sent_gb"] = 0.0
        info["net_recv_gb"] = 0.0

    # --- Determine Tier and Worker Counts ---
    cores = info["logical_cores"]
    ram = info["ram_total_gb"]
    gpu_vram = info["gpu_vram_total_gb"]
    has_cuda = info["gpu_has_cuda"]

    # GPU VRAM boosts tier: 8GB GPU + 16 cores = HIGH
    effective_power = cores + (gpu_vram * 2)  # GPU VRAM counts as 2x cores

    if (cores >= 16 and ram >= 32) or (effective_power >= 32 and gpu_vram >= 4):
        tier = "HIGH"
        process_workers = min(cores // 2, 16)
        io_workers = min(cores // 2, 16)
        analysis_workers = min(cores // 2, 12)
        scanner_workers = min(cores // 2, 12)
        correlation_workers = min(cores // 3, 8)
        position_workers = min(cores // 6, 4)
        max_symbols = 30
        scan_interval_parallel = 15
        brain_timeout = 20
        process_timeout = 25
        gpu_batch_size = min(int(gpu_vram * 64) if gpu_vram > 0 else 256, 1024) if has_cuda else 64
        gpu_enabled = has_cuda and gpu_vram >= 4
    elif cores >= 8 and ram >= 16:
        tier = "MEDIUM"
        process_workers = min(cores // 2, 10)
        io_workers = min(cores // 2, 10)
        analysis_workers = min(cores // 3, 8)
        scanner_workers = min(cores // 2, 8)
        correlation_workers = min(cores // 4, 6)
        position_workers = min(cores // 8, 3)
        max_symbols = 20
        scan_interval_parallel = 20
        brain_timeout = 30
        process_timeout = 30
        gpu_batch_size = min(int(gpu_vram * 32) if gpu_vram > 0 else 128, 512) if has_cuda else 32
        gpu_enabled = has_cuda and gpu_vram >= 2
    else:
        tier = "LOW"
        process_workers = min(cores, 4)
        io_workers = min(cores, 4)
        analysis_workers = min(cores // 2, 4)
        scanner_workers = min(cores // 2, 4)
        correlation_workers = min(cores // 3, 3)
        position_workers = 2
        max_symbols = 10
        scan_interval_parallel = 30
        brain_timeout = 45
        process_timeout = 45
        gpu_batch_size = min(int(gpu_vram * 16) if gpu_vram > 0 else 32, 256) if has_cuda else 32
        gpu_enabled = has_cuda and gpu_vram >= 2

    info["tier"] = tier
    info["process_workers"] = process_workers
    info["io_workers"] = io_workers
    info["analysis_workers"] = analysis_workers
    info["scanner_workers"] = scanner_workers
    info["correlation_workers"] = correlation_workers
    info["position_workers"] = position_workers
    info["max_symbols"] = max_symbols
    info["scan_interval_parallel"] = scan_interval_parallel
    info["brain_timeout"] = brain_timeout
    info["process_timeout"] = process_timeout
    info["gpu_batch_size"] = gpu_batch_size
    info["gpu_enabled"] = gpu_enabled

    return info


def save_system_to_env(system_info, env_path=".env"):
    """Write detected system parameters to .env file for reference."""
    env_vars = {
        "# === AUTO-DETECTED SYSTEM INFO ===": "",
        "SYSTEM_TIER": system_info["tier"],
        "SYSTEM_CPU_NAME": system_info["cpu_name"],
        "SYSTEM_CPU_CORES_PHYSICAL": str(system_info["physical_cores"]),
        "SYSTEM_CPU_CORES_LOGICAL": str(system_info["logical_cores"]),
        "SYSTEM_CPU_FREQ_MHZ": str(system_info["cpu_freq_current_mhz"]),
        "SYSTEM_CPU_FREQ_MAX_MHZ": str(system_info["cpu_freq_max_mhz"]),
        "SYSTEM_CPU_ARCH": system_info["arch"],
        "SYSTEM_CPU_ARCH_BITS": system_info["arch_bits"],
        "SYSTEM_CPU_USAGE_PCT": str(system_info["cpu_usage_percent"]),
        "SYSTEM_RAM_TOTAL_GB": str(system_info["ram_total_gb"]),
        "SYSTEM_RAM_AVAIL_GB": str(system_info["ram_available_gb"]),
        "SYSTEM_RAM_USED_GB": str(system_info["ram_used_gb"]),
        "SYSTEM_RAM_USAGE_PCT": str(system_info["ram_usage_percent"]),
        "SYSTEM_SWAP_TOTAL_GB": str(system_info["swap_total_gb"]),
        "SYSTEM_SWAP_USED_GB": str(system_info["swap_used_gb"]),
        "SYSTEM_DISK_TOTAL_GB": str(system_info["disk_total_gb"]),
        "SYSTEM_DISK_FREE_GB": str(system_info["disk_free_gb"]),
        "SYSTEM_DISK_USAGE_PCT": str(system_info["disk_usage_percent"]),
        "SYSTEM_NET_SENT_GB": str(system_info["net_sent_gb"]),
        "SYSTEM_NET_RECV_GB": str(system_info["net_recv_gb"]),
        "# === GPU INFO ===": "",
        "SYSTEM_GPU_COUNT": str(system_info["gpu_count"]),
        "SYSTEM_GPU_NAME": system_info["gpu_name"],
        "SYSTEM_GPU_VENDOR": system_info["gpu_vendor"],
        "SYSTEM_GPU_VRAM_TOTAL_MB": str(system_info["gpu_vram_total_mb"]),
        "SYSTEM_GPU_VRAM_TOTAL_GB": str(system_info["gpu_vram_total_gb"]),
        "SYSTEM_GPU_CORES": str(system_info["gpu_cores"]),
        "SYSTEM_GPU_COMPUTE_CAPABILITY": system_info["gpu_compute_capability"],
        "SYSTEM_GPU_DRIVER_VERSION": system_info["gpu_driver_version"],
        "SYSTEM_GPU_CLOCK_MHZ": str(system_info["gpu_clock_mhz"]),
        "SYSTEM_GPU_MEMORY_CLOCK_MHZ": str(system_info["gpu_memory_clock_mhz"]),
        "SYSTEM_GPU_POWER_DRAW_W": str(system_info["gpu_power_draw_w"]),
        "SYSTEM_GPU_TEMP_C": str(system_info["gpu_temp_c"]),
        "SYSTEM_GPU_UTILIZATION_PCT": str(system_info["gpu_utilization_pct"]),
        "SYSTEM_GPU_HAS_CUDA": str(system_info["gpu_has_cuda"]),
        "SYSTEM_GPU_HAS_OPENCL": str(system_info["gpu_has_opencl"]),
        "SYSTEM_GPU_ENABLED": str(system_info["gpu_enabled"]),
        "SYSTEM_GPU_BATCH_SIZE": str(system_info["gpu_batch_size"]),
        "# === PLATFORM INFO ===": "",
        "SYSTEM_PLATFORM": system_info["platform"],
        "SYSTEM_PLATFORM_RELEASE": system_info["platform_release"],
        "SYSTEM_PLATFORM_VERSION": system_info["platform_version"],
        "SYSTEM_PYTHON_VERSION": system_info["python_version"],
        "SYSTEM_HOSTNAME": system_info["hostname"],
        "# === AUTO-TUNED WORKERS ===": "",
        "SYSTEM_PROCESS_WORKERS": str(system_info["process_workers"]),
        "SYSTEM_IO_WORKERS": str(system_info["io_workers"]),
        "SYSTEM_ANALYSIS_WORKERS": str(system_info["analysis_workers"]),
        "SYSTEM_SCANNER_WORKERS": str(system_info["scanner_workers"]),
        "SYSTEM_CORRELATION_WORKERS": str(system_info["correlation_workers"]),
        "SYSTEM_POSITION_WORKERS": str(system_info["position_workers"]),
        "SYSTEM_MAX_SYMBOLS": str(system_info["max_symbols"]),
        "SYSTEM_SCAN_INTERVAL_PARALLEL": str(system_info["scan_interval_parallel"]),
        "SYSTEM_BRAIN_TIMEOUT": str(system_info["brain_timeout"]),
        "SYSTEM_PROCESS_TIMEOUT": str(system_info["process_timeout"]),
    }

    # Read existing .env to preserve user secrets
    existing_lines = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                existing_lines.append(line)

    # Build new .env content - keep non-system lines, replace system lines
    new_lines = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped:
            if stripped.startswith("# ==="):
                continue
            if stripped and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key.startswith("SYSTEM_"):
                    continue
        new_lines.append(line)

    # Remove trailing empty lines
    while new_lines and new_lines[-1].strip() == "":
        new_lines.pop()

    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines.append("\n")
    new_lines.append("\n")

    # Add detected system info
    for key, value in env_vars.items():
        if key.startswith("#"):
            new_lines.append(f"{key}\n")
        else:
            new_lines.append(f"{key}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)

    return env_path


# Lazy-initialized system detection (runs on first access)
_SYSTEM = None

def _get_system():
    global _SYSTEM
    if _SYSTEM is None:
        _SYSTEM = detect_system()
        try:
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            save_system_to_env(_SYSTEM, env_path)
        except Exception as e:
            logger.debug("Failed to save system info to .env: %s", e)
    return _SYSTEM

# ==========================================
# TRADING CONSTANTS
# ==========================================
INITIAL_BALANCE = 10000.0

# ==========================================
# MAGIC NUMBER SYSTEM (from magic_database.py)
# Format: BBMMSSSSSS (10 digits)
#   BB     = brain version (01-11)
#   MM     = trading method (01-24)
#   SSSSSS = symbol index (000001-070036)
# Max value: 112470036 < 4,294,967,295 (32-bit safe)
# Total combinations: 11 brains × 24 methods × 69,568+ symbols
# ==========================================

from magic_database import (
    BRAINS, ALL_METHODS as METHODS,
    SYMBOL_INDEX, TOTAL_SYMBOLS, TOTAL_COMBINATIONS,
    get_magic_number, get_magic_info, get_magic_category,
    magic_belongs_to_brain, magic_belongs_to_method,
    is_system_magic, save_database, load_database,
)

# Legacy constants (imported from magic_database for backward compatibility)
from magic_database import (
    MAGIC_NUMBER, MAGIC_SCALPING, MAGIC_DAY_TRADING, MAGIC_SWING, MAGIC_POSITION,
    MAGIC_TECHNICAL, MAGIC_FUNDAMENTAL, MAGIC_SENTIMENT, MAGIC_TREND,
    MAGIC_COUNTER_TREND, MAGIC_BREAKOUT, MAGIC_RANGE, MAGIC_TMC,
    MAGIC_BRAIN_V1, MAGIC_BRAIN_V2, MAGIC_BRAIN_V3, MAGIC_BRAIN_V4,
    MAGIC_BRAIN_V5, MAGIC_BRAIN_V6, MAGIC_BRAIN_V7, MAGIC_BRAIN_V8,
    MAGIC_BRAIN_V9,
)

# Build ALL_MAGIC_NUMBERS from database
ALL_MAGIC_NUMBERS = set()
ALL_MAGIC_NUMBERS.add(MAGIC_NUMBER)
ALL_MAGIC_NUMBERS.update([
    MAGIC_SCALPING, MAGIC_DAY_TRADING, MAGIC_SWING, MAGIC_POSITION,
    MAGIC_TECHNICAL, MAGIC_FUNDAMENTAL, MAGIC_SENTIMENT, MAGIC_TREND,
    MAGIC_COUNTER_TREND, MAGIC_BREAKOUT, MAGIC_RANGE, MAGIC_TMC,
    MAGIC_BRAIN_V1, MAGIC_BRAIN_V2, MAGIC_BRAIN_V3, MAGIC_BRAIN_V4,
    MAGIC_BRAIN_V5, MAGIC_BRAIN_V6, MAGIC_BRAIN_V7, MAGIC_BRAIN_V8,
    MAGIC_BRAIN_V9,
])

# ==========================================
# API CONFIGURATION
# ==========================================
AI_BASE_URL = os.environ.get("AI_BASE_URL", "http://127.0.0.1:3001/v1")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
EIA_API_KEY = os.environ.get("EIA_API_KEY", "")
CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "http://localhost:8123")

# ==========================================
# SYMBOL CONFIGURATION
# ==========================================
SCAN_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDCAD", "AUDUSD", "NZDUSD"]
PREFERRED_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDCAD", "AUDUSD", "USDCHF", "NZDUSD",
    "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURAUD", "GBPAUD",
    "XAGUSD", "US30", "NAS100", "SPX500", "BTCUSD", "ETHUSD"
]

# ==========================================
# CORRELATION GROUPS (single source of truth)
# ==========================================
CORRELATION_GROUPS = {
    "USD_INDEX": {"symbols": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDJPY", "USDCHF"], "inverse": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"]},
    "RISK_ON": {"symbols": ["AUDUSD", "NZDUSD", "US500", "NAS100", "BTCUSD"], "inverse": []},
    "SAFE_HAVEN": {"symbols": ["USDJPY", "USDCHF", "XAUUSD", "XAGUSD"], "inverse": ["USDJPY"]},
    "COMMODITY_DOLLAR": {"symbols": ["AUDUSD", "USDCAD", "XAUUSD", "XAGUSD", "USOIL"], "inverse": ["USDCAD"]},
    "EQUITY_CRYPTO": {"symbols": ["US500", "NAS100", "BTCUSD", "ETHUSD"], "inverse": []},
    "BOND_PROXY": {"symbols": ["USDJPY", "XAUUSD", "US30"], "inverse": ["USDJPY"]},
}

# ==========================================
# RISK PARAMETERS (auto-tuned from system)
# ==========================================
MAX_SPREAD_POINTS = 25
MAX_SYMBOLS = _get_system()["max_symbols"]
COOLDOWN_SECONDS = 10
SCAN_INTERVAL = 1
MIN_CONFIDENCE_TO_TRADE = 0.55
STATUS_INTERVAL = 60
DASHBOARD_PORT = 8050
EXPORT_INTERVAL = 1.0
SCAN_INTERVAL_PARALLEL = _get_system()["scan_interval_parallel"]

# Order rate limiting (global)
MAX_ORDERS_PER_SECOND = 5
MAX_ORDERS_PER_MINUTE = 30

# Centralized lookback constants (bars per horizon)
LOOKBACK_CANDLES = 500       # Standard lookback for all timeframes
LOOKBACK_MICRO = 100    # M1-M15: fast momentum
LOOKBACK_MEDIUM = 150   # M30-H4: trend structures
LOOKBACK_MACRO = 50     # D1-W1: macro regime

# Parallel config (auto-detected from system capacity)
ANALYSIS_WORKERS = _get_system()["analysis_workers"]
POSITION_WORKERS = _get_system()["position_workers"]
SCANNER_WORKERS = _get_system()["scanner_workers"]
CORRELATION_WORKERS = _get_system()["correlation_workers"]
MONITOR_INTERVAL = 5
BRAIN_TIMEOUT = _get_system()["brain_timeout"]
PROCESS_TIMEOUT = _get_system()["process_timeout"]

# GPU settings (auto-detected)
GPU_ENABLED = _get_system()["gpu_enabled"]
GPU_BATCH_SIZE = _get_system()["gpu_batch_size"]

# System info (for logging/display)
SYSTEM_TIER = _get_system()["tier"]
SYSTEM_CPU_NAME = _get_system()["cpu_name"]
SYSTEM_CPU_COUNT = _get_system()["logical_cores"]
SYSTEM_CPU_PHYSICAL = _get_system()["physical_cores"]
SYSTEM_CPU_FREQ = _get_system()["cpu_freq_current_mhz"]
SYSTEM_CPU_FREQ_MAX = _get_system()["cpu_freq_max_mhz"]
SYSTEM_CPU_ARCH = _get_system()["arch"]
SYSTEM_CPU_USAGE = _get_system()["cpu_usage_percent"]
SYSTEM_MEMORY_GB = _get_system()["ram_total_gb"]
SYSTEM_MEMORY_AVAIL_GB = _get_system()["ram_available_gb"]
SYSTEM_MEMORY_PCT = _get_system()["ram_usage_percent"]
SYSTEM_SWAP_GB = _get_system()["swap_total_gb"]
SYSTEM_DISK_TOTAL_GB = _get_system()["disk_total_gb"]
SYSTEM_DISK_FREE_GB = _get_system()["disk_free_gb"]
SYSTEM_DISK_PCT = _get_system()["disk_usage_percent"]
SYSTEM_PLATFORM = _get_system()["platform"]
SYSTEM_HOSTNAME = _get_system()["hostname"]
SYSTEM_GPU_COUNT = _get_system()["gpu_count"]
SYSTEM_GPU_NAME = _get_system()["gpu_name"]
SYSTEM_GPU_VENDOR = _get_system()["gpu_vendor"]
SYSTEM_GPU_VRAM_GB = _get_system()["gpu_vram_total_gb"]
SYSTEM_GPU_CORES = _get_system()["gpu_cores"]
SYSTEM_GPU_COMPUTE_CAP = _get_system()["gpu_compute_capability"]
SYSTEM_GPU_DRIVER = _get_system()["gpu_driver_version"]
SYSTEM_GPU_CLOCK = _get_system()["gpu_clock_mhz"]
SYSTEM_GPU_MEM_CLOCK = _get_system()["gpu_memory_clock_mhz"]
SYSTEM_GPU_POWER = _get_system()["gpu_power_draw_w"]
SYSTEM_GPU_TEMP = _get_system()["gpu_temp_c"]
SYSTEM_GPU_UTIL = _get_system()["gpu_utilization_pct"]
SYSTEM_GPU_CUDA = _get_system()["gpu_has_cuda"]
SYSTEM_GPU_OPENCL = _get_system()["gpu_has_opencl"]
PROCESS_WORKERS = _get_system()["process_workers"]
IO_WORKERS = _get_system()["io_workers"]

# ==========================================
# TIMEFRAME CONFIGURATION (per brain/method)
# ==========================================
# Maps brain + method to optimal timeframes
# Format: {brain: {method: [primary, confirmation1, confirmation2, execution]}}
BRAIN_METHOD_TIMEFRAMES = {
    "v1": {
        "scalping": ["M1", "M5", "M15", "M1"],
        "day_trading": ["M5", "M15", "M30", "M5"],
        "swing": ["H4", "H1", "D1", "H4"],
        "position": ["D1", "W1", "MN1", "D1"],
        "technical": ["H1", "H4", "M15", "H1"],
        "trend": ["H1", "H4", "D1", "H1"],
        "counter_trend": ["M30", "H1", "H4", "M30"],
        "breakout": ["H1", "H4", "M15", "H1"],
    },
    "v2": {
        "scalping": ["M5", "M15", "M1", "M5"],
        "day_trading": ["M15", "H1", "M5", "M15"],
        "swing": ["H1", "H4", "D1", "H1"],
        "technical": ["H1", "H4", "M15", "H1"],
        "trend": ["H1", "H4", "D1", "H1"],
    },
    "v3": {
        "scalping": ["M5", "M15", "M1", "M5"],
        "day_trading": ["M5", "M15", "M30", "M5"],
    },
    "v4": {
        "technical": ["H1", "H4", "D1", "H1"],
        "swing": ["H4", "D1", "W1", "H4"],
    },
    "v5": {
        "swing": ["H4", "D1", "W1", "H4"],
        "position": ["D1", "W1", "MN1", "D1"],
    },
    "v6": {
        "scalping": ["M5", "M15", "M1", "M5"],
        "day_trading": ["M5", "M15", "M30", "M5"],
    },
    "v7": {
        "technical": ["H1", "H4", "D1", "H1"],
        "swing": ["H4", "D1", "W1", "H4"],
        "trend": ["H1", "H4", "D1", "H1"],
    },
    "v8": {
        "swing": ["H4", "D1", "W1", "H4"],
        "position": ["D1", "W1", "MN1", "D1"],
    },
    "v9": {
        "scalping": ["M1", "M5", "M1", "M1"],
        "day_trading": ["M5", "M15", "M5", "M5"],
    },
    "v10": {
        "technical": ["M15", "H1", "H4", "H1"],
        "trend": ["H1", "H4", "D1", "H1"],
        "swing": ["H4", "D1", "W1", "H4"],
    },
    "v11": {
        "technical": ["H1", "H4", "M15", "H1"],
        "trend": ["H1", "H4", "D1", "H1"],
        "swing": ["H4", "D1", "W1", "H4"],
        "scalping": ["M1", "M5", "M15", "M1"],
        "day_trading": ["M5", "M15", "M30", "M5"],
        "breakout": ["H1", "H4", "M15", "H1"],
        "counter_trend": ["M30", "H1", "H4", "M30"],
        "position": ["D1", "W1", "MN1", "D1"],
        "momentum": ["H1", "H4", "M15", "H1"],
        "mean_reversion": ["M30", "H1", "M30", "M30"],
        "volatility": ["M30", "H1", "H4", "M30"],
        "range": ["M30", "H1", "M30", "M30"],
        "fundamental": ["D1", "W1", "D1", "D1"],
        "sentiment": ["H4", "D1", "H4", "H4"],
    },
}

# Default timeframes for unknown combinations
DEFAULT_TIMEFRAMES = ["H1", "H4", "D1", "H1"]

# MT5 timeframe constants
MT5_TIMEFRAMES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440, "W1": 10080, "MN1": 43200,
}

def get_timeframes(brain="v11", method="technical"):
    """Get optimal timeframes for a brain+method combination."""
    brain_tfs = BRAIN_METHOD_TIMEFRAMES.get(str(brain).lower(), {})
    return brain_tfs.get(str(method).lower(), DEFAULT_TIMEFRAMES)

def get_mt5_timeframe(tf_name):
    """Convert timeframe name to MT5 constant."""
    return MT5_TIMEFRAMES.get(tf_name.upper(), 60)  # Default to H1

# ==========================================
# PATHS
# ==========================================
DATA_DIR = os.path.join(os.path.dirname(__file__), "brain_data")
LOG_DIR = os.path.join(DATA_DIR, "logs")

# ==========================================
# CONFIG VALIDATION (fails fast on bad values)
# ==========================================
def _validate_config():
    """Validate all critical config values at import time."""
    errors = []

    def check(name, value, lo, hi):
        if not isinstance(value, (int, float)):
            errors.append(f"{name}={value!r} is not numeric")
        elif value < lo or value > hi:
            errors.append(f"{name}={value} out of range [{lo}, {hi}]")

    check("MAX_SPREAD_POINTS", MAX_SPREAD_POINTS, 1, 1000)
    check("MAX_SYMBOLS", MAX_SYMBOLS, 1, 100)
    check("COOLDOWN_SECONDS", COOLDOWN_SECONDS, 0, 3600)
    check("MIN_CONFIDENCE_TO_TRADE", MIN_CONFIDENCE_TO_TRADE, 0.01, 1.0)
    check("MAX_ORDERS_PER_SECOND", MAX_ORDERS_PER_SECOND, 1, 100)
    check("MAX_ORDERS_PER_MINUTE", MAX_ORDERS_PER_MINUTE, 1, 1000)
    check("LOOKBACK_MICRO", LOOKBACK_MICRO, 10, 1000)
    check("LOOKBACK_MEDIUM", LOOKBACK_MEDIUM, 10, 1000)
    check("LOOKBACK_MACRO", LOOKBACK_MACRO, 10, 1000)
    check("ANALYSIS_WORKERS", ANALYSIS_WORKERS, 1, 64)
    check("SCANNER_WORKERS", SCANNER_WORKERS, 1, 64)
    check("DASHBOARD_PORT", DASHBOARD_PORT, 1024, 65535)
    check("BRAIN_TIMEOUT", BRAIN_TIMEOUT, 1, 300)
    check("MONITOR_INTERVAL", MONITOR_INTERVAL, 1, 300)

    if errors:
        raise ValueError("Config validation failed:\n  " + "\n  ".join(errors))

_validate_config()
