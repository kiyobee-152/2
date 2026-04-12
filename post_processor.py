# -*- coding: utf-8 -*-
"""
后处理模块
提供检测结果的后处理功能：保存结果、导出报告、统计信息等

本模块负责管理目标检测完成后的所有下游处理任务，是整个系统的"数据出口"。
包含两个核心类：
  - DetectionResult（检测结果数据类）：表示单条检测记录的数据结构，封装了类别名称、
    置信度、边界框坐标、时间戳和帧ID等信息，并提供了 to_dict() 方法用于序列化。
  - PostProcessor（后处理器类）：管理所有检测结果的存储、统计和导出，维护一个
    detection_history 列表作为检测历史记录，以及一个 statistics 字典进行类别计数。
    提供了多种格式的导出能力（TXT 报告、CSV 表格、JSON 数据）和图像/视频保存功能。

在系统中的调用位置（main.py）：
  - Ui_MainWindow.__init__ 中创建 PostProcessor 实例
  - start_camera() / start_video() / start_image() 中每帧检测后调用 add_detection() 记录结果
  - get_result_str() 中调用 get_statistics() 获取累计统计用于界面显示
  - GUI 按钮分别绑定 export_report()、export_csv()、export_json()、save_current_image()
  - "清空检测记录"按钮绑定 clear_history()

依赖关系：
  - os：文件路径操作、目录创建
  - json：JSON 格式导出
  - csv：CSV 格式导出
  - cv2（OpenCV）：图像和视频的读写保存
  - numpy：图像数组类型
  - datetime：时间戳生成
  - collections.defaultdict：类别计数的自动初始化字典
"""
import os
import json
import csv
import threading
import cv2
import numpy as np
from datetime import datetime
# List: 列表类型提示
# Dict: 字典类型提示
# Optional: 可选参数（可以为 None）
# Tuple: 元组类型提示（如边界框坐标）
from typing import List, Dict, Optional, Tuple
# defaultdict: 当访问不存在的键时自动用默认工厂函数初始化
# 这里用 defaultdict(int) 使所有新键的初始值为 0，省去手动判断键是否存在的逻辑
from collections import defaultdict


# =============================================================================
# DetectionResult - 检测结果数据类
# =============================================================================
# 表示一条完整的目标检测记录。系统中每检测到一个目标就创建一个 DetectionResult 实例，
# 并追加到 PostProcessor.detection_history 列表中。
# 
# 数据结构设计：
#   class_name  - 目标类别（如 "bolt" 或 "bulk"）
#   confidence  - 检测置信度（0.0 ~ 1.0）
#   bbox        - 边界框像素坐标 (x1, y1, x2, y2)，左上角和右下角
#   timestamp   - 检测发生的时间（字符串格式："YYYY-MM-DD HH:MM:SS"）
#   frame_id    - 该检测所在的视频帧编号（图片检测时为 0）
class DetectionResult:
    """检测结果数据类"""
    
    def __init__(self, class_name: str, confidence: float, bbox: Tuple[int, int, int, int],
                 timestamp: Optional[str] = None, frame_id: Optional[int] = None):
        """
        初始化检测结果
        
        Args:
            class_name: 类别名称
            confidence: 置信度
            bbox: 边界框 (x1, y1, x2, y2)
            timestamp: 时间戳
            frame_id: 帧ID
        """
        # 目标的类别名称���来自 class_names.txt 中的定义
        # 本项目中为 "bolt"（锚杆/螺栓）或 "bulk"（散料/块状物）
        self.class_name = class_name
        # 模型对该检测结果的置信度分数，值越高表示模型越确信
        self.confidence = confidence
        # 边界框坐标元组 (x1, y1, x2, y2)
        # (x1, y1) 为左上角像素坐标，(x2, y2) 为右下角像素坐标
        # 坐标已经通过 scale_coords 映射回了原始图像尺寸
        self.bbox = bbox
        # 检测时间戳：如果外部传入则使用传入值，否则取当前系统时间
        # 格式为 "2026-02-06 14:30:00" 这样的可读字符串
        self.timestamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 帧ID：标识该检测发生在视频的第几帧
        # 对于图片检测固定为 0；对于视频/摄像头检测，从 0 开始递增
        # 可用于后续按帧回溯定位检测结果
        self.frame_id = frame_id
    
    def to_dict(self) -> Dict:
        """
        将检测结果转换为字典格式
        
        用于 JSON 序列化导出。将所有属性转为 Python 基本类型，
        其中 bbox 从元组转为列表（JSON 不支持元组），
        confidence 显式转为 float（避免 numpy float 类型序列化问题）。
        
        Returns:
            包含所有检测信息的字典，键为英文字段名
        """
        return {
            'class_name': self.class_name,
            'confidence': float(self.confidence),
            'bbox': list(self.bbox),
            'timestamp': self.timestamp,
            'frame_id': self.frame_id
        }


# =============================================================================
# PostProcessor - 后处理器类
# =============================================================================
# 这是后处理模块的核心��，承担以下职责：
# 1. 结果收集：通过 add_detection() 接收每帧的检测结果并存入历史记录
# 2. 实时统计：维护 statistics 字典，按类别实时累加检测数量
# 3. 结果导出：支持 TXT 报告、CSV 表格、JSON 数据三种格式导出
# 4. 图像/视频保存：保存带有检测框标注的图像或视频
# 5. 历史管理：支持清空历史记录、查询最近检测结果
#
# 数据存储结构：
#   detection_history: List[DetectionResult] - 按时间顺序存储的所有检测记录列表
#   statistics: Dict[str, int] - 各类别的累计检测数量（如 {"bolt": 152, "bulk": 38}）
class PostProcessor:
    """后处理器类"""
    
    def __init__(self, output_dir: str = './results'):
        """
        初始化后处理器
        
        Args:
            output_dir: 输出目录
        """
        # 所有导出文件的根目录，默认为程序运行目录下的 ./results/
        # 图像保存在 output_dir/images/，视频保存在 output_dir/videos/，
        # 报告和数据文件直接保存在 output_dir/ 下
        self.output_dir = output_dir
        # 检测历史记录列表：按时间顺序存储所有 DetectionResult 实例
        # 每检测到一个目标就追加一条记录，一帧中可能有多个目标（多条记录）
        self.detection_history: List[DetectionResult] = []
        # 类别统计字典：键为类别名称（str），值为累计检测次数（int）
        # 使用 defaultdict(int) 使得首次访问新类别时自动初始化为 0，
        # 无需手动判断键是否存在，直接 += 1 即可
        self.statistics: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        # 创建输出根目录（如果不存在的话）
        # exist_ok=True 表示目录已存在时不报错
        os.makedirs(output_dir, exist_ok=True)
    
    def get_history_count(self) -> int:
        with self._lock:
            return len(self.detection_history)
    
    def get_detection_history_copy(self) -> List[DetectionResult]:
        with self._lock:
            return list(self.detection_history)
    
    def add_detection(self, result_list: List[List], frame_id: Optional[int] = None):
        """
        添加检测结果到历史记录
        
        这是后处理器最常被调用的方法，在 main.py 的每帧检测循环中，
        模型推理完成后立即调用此方法将结果存入。
        
        同一帧中检测到的所有目标共享相同的时间戳和帧ID，
        但每个目标各自创建一个独立的 DetectionResult 实例。
        
        同时更新 statistics 字典中对应类别的累计计数。
        
        Args:
            result_list: 检测结果列表，来自 detector.inference_image() 的输出
                         每个元素格式: [class_name, confidence, x1, y1, x2, y2]
            frame_id: 当前帧的编号，由 main.py 中的 current_frame_id 计数器提供
        """
        # 为当前帧的所有检测结果生成统一的时间戳
        # 同一帧的所有目标共享同一个时间戳，便于后续按时间分组查询
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            for result in result_list:
                det_result = DetectionResult(
                    class_name=result[0],
                    confidence=result[1],
                    bbox=(result[2], result[3], result[4], result[5]),
                    timestamp=timestamp,
                    frame_id=frame_id
                )
                self.detection_history.append(det_result)
                self.statistics[result[0]] += 1
    
    def get_statistics(self) -> Dict[str, int]:
        """
        获取统计信息
        
        返回各类别的累计检测数量。在 main.py 的 get_result_str() 方法中调用，
        用于在 GUI 右侧的"结果统计"文本框中显示累计统计数据。
        
        Returns:
            普通字典（非 defaultdict），键为类别名称，值为累计检测次数
            例如：{"bolt": 152, "bulk": 38}
        """
        with self._lock:
            return dict(self.statistics)
    
    def get_detection_summary(self) -> str:
        """
        获取检测摘要文本
        
        生成人类可读的统计摘要字符串，包含各类别的检测数量和占比百分比。
        在 export_report() 导出报告时作为报告头部的统计概览。
        
        Returns:
            多行文本字符串，格式如：
            "检测统计:
             总计: 190
             bolt: 152 (80.0%)
             bulk: 38 (20.0%)"
            如果没有检测记录则返回 "未检测到目标"
        """
        with self._lock:
            stats = dict(self.statistics)
        if not stats:
            return "未检测到目标"
        summary = "检测统计:\n"
        total = sum(stats.values())
        summary += f"总计: {total}\n"
        for class_name, count in stats.items():
            percentage = (count / total * 100) if total > 0 else 0
            summary += f"{class_name}: {count} ({percentage:.1f}%)\n"
        return summary
    
    def save_image(self, image: np.ndarray, filename: Optional[str] = None, 
                   subfolder: str = 'images') -> str:
        """
        保存图像
        
        将带有检测框标注的图像保存到磁盘。默认保存到 output_dir/images/ 子目录。
        文件名如果未指定则自动以当前时间戳命名（如 "detection_20260206_143000.jpg"）。
        
        Args:
            image: 图像数组，OpenCV BGR 格式的 numpy 数组
            filename: 文件名，None则自动生成带时间戳的文件名
            subfolder: 子文件夹名称，默认 'images'，保存路径为 output_dir/images/
            
        Returns:
            保存的文件完整路径
        """
        # 拼接完整的保存目录路径：output_dir + subfolder
        folder = os.path.join(self.output_dir, subfolder)
        # 确保保存目录存在
        os.makedirs(folder, exist_ok=True)
        
        # 如果未指定文件名，自动生成带时间戳的文件名以避免重名覆盖
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"detection_{timestamp}.jpg"
        
        # 拼接完整文件路径并保存
        filepath = os.path.join(folder, filename)
        # cv2.imwrite 会根据文件扩展名自动选择编码格式（.jpg → JPEG, .png → PNG）
        cv2.imwrite(filepath, image)
        return filepath
    
    def save_video(self, frames: List[np.ndarray], filename: Optional[str] = None,
                   fps: int = 30, subfolder: str = 'videos') -> str:
        """
        保存视频
        
        将一组帧序列编码保存为 MP4 视频文件。可用于保存检测过程的录像回放。
        
        Args:
            frames: 帧列表，每个元素为 OpenCV BGR 格式的 numpy 数组
                    所有帧应具有相同的分辨率
            filename: 文件名，None 则自动生成
            fps: 输出视频的帧率，默认 30fps
            subfolder: 子文件夹名称，默认 'videos'
            
        Returns:
            保存的文件完整路径；如果 frames 为空则返回空字符串
        """
        # 空帧列表无法创建视频，直接返回
        if not frames:
            return ""
        
        # 拼接并创建保存目录
        folder = os.path.join(self.output_dir, subfolder)
        os.makedirs(folder, exist_ok=True)
        
        # 自动生成文件名
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"detection_{timestamp}.mp4"
        
        filepath = os.path.join(folder, filename)
        # 从第一帧获取视频分辨率（所有帧应为相同尺寸）
        # frame.shape 为 (height, width, channels)
        height, width = frames[0].shape[:2]
        
        # 创建视频写入器
        # 'mp4v' 是 MPEG-4 编码的 FourCC 标识符
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        # VideoWriter 参数：输出路径, 编码格式, 帧率, (宽, 高)
        out = cv2.VideoWriter(filepath, fourcc, fps, (width, height))
        
        # 逐帧写入视频
        for frame in frames:
            out.write(frame)
        
        # 释放 VideoWriter 资源（刷新缓冲区并关闭文件）
        out.release()
        return filepath
    
    def export_json(self, filename: Optional[str] = None) -> str:
        """
        导出检测结果为JSON格式
        
        JSON 文件包含三个顶级字段：
        1. statistics: 各类别的累计检测数量（字典）
        2. total_detections: 总检测记录条数（整数）
        3. detections: 所有检测记录的详细列表（每条记录包含类别、置信度、坐标、时间戳、帧ID）
        
        JSON 格式适合程序化读取和进一步的数据分析处理。
        
        在 main.py 中通过 GUI 的"导出JSON"按钮或菜单栏"文件→导出JSON"触发调用。
        
        Args:
            filename: 输出文件名（完整路径或仅文件名）。
                      如果传入完整路径则直接使用；如果为 None 则自动生成
            
        Returns:
            保存的文件完整路径
        """
        # 自动生成带时间戳的文件名
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"detections_{timestamp}.json"
        
        filepath = os.path.join(self.output_dir, filename)
        
        with self._lock:
            stats = dict(self.statistics)
            dets = [det.to_dict() for det in self.detection_history]
        data = {
            'statistics': stats,
            'total_detections': len(dets),
            'detections': dets,
        }
        
        # 写入 JSON 文件
        # ensure_ascii=False: 允许中文等非 ASCII 字符直接写入（不转义为 \uXXXX）
        # indent=2: 格式化缩进 2 个空格，使文件可读性更好
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return filepath
    
    def export_csv(self, filename: Optional[str] = None) -> str:
        """
        导出检测结果为CSV格式
        
        CSV 文件的列结构：
        时间戳 | 帧ID | 类别 | 置信度 | X1 | Y1 | X2 | Y2
        
        CSV 格式适合用 Excel 打开查看，也方便用 pandas 等工具进行数据分析。
        
        在 main.py 中通过 GUI 的"导出CSV"按钮触发调用。
        
        Args:
            filename: 输出文件名，None 则自动生成
            
        Returns:
            保存的文件完整路径
        """
        # 自动生成带时间戳的文件名
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"detections_{timestamp}.csv"
        
        filepath = os.path.join(self.output_dir, filename)
        
        with self._lock:
            history_copy = list(self.detection_history)
        
        # 写入 CSV 文件
        # newline='': 防止 Windows 下 csv.writer 产生多余空行
        # encoding='utf-8-sig': 使用带 BOM 的 UTF-8 编码
        #   BOM（字节顺序标记）使 Excel 能正确识别 UTF-8 编码，避免中文乱码
        #   普通 'utf-8' 编码在 Excel 中打开可能出现中文显示异常
        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            # 写入表头行（中文列名）
            writer.writerow(['时间戳', '帧ID', '类别', '置信度', 'X1', 'Y1', 'X2', 'Y2'])
            
            # 逐条写入检测记录
            for det in history_copy:
                writer.writerow([
                    det.timestamp,
                    # 帧ID 如果为 None（理论上不应该，但做防御处理），则写入空字符串
                    det.frame_id if det.frame_id is not None else '',
                    det.class_name,
                    det.confidence,
                    # 边界框四个坐标值，bbox 是元组 (x1, y1, x2, y2)
                    det.bbox[0], det.bbox[1],
                    det.bbox[2], det.bbox[3]
                ])
        
        return filepath
    
    def export_report(self, filename: Optional[str] = None) -> str:
        """
        导出文本报告
        
        生成人类可读的纯文本检测报告，包含：
        1. 报告标题和生成时间
        2. 检测统计摘要（各类别数量和占比）
        3. 每条检测记录的详细信息（时间、帧ID、类别、置信度、坐标位置）
        
        报告格式示例：
        ==================================================
        皮带传送带锚杆检测报告
        ==================================================
        
        生成时间: 2026-02-06 14:30:00
        
        检测统计:
        总计: 190
        bolt: 152 (80.0%)
        bulk: 38 (20.0%)
        
        --------------------------------------------------
        详细检测记录:
        --------------------------------------------------
        
        检测 #1:
          时间: 2026-02-06 14:25:30
          帧ID: 0
          类别: bolt
          置信度: 0.92
          位置: (120, 85) - (250, 310)
        ...
        
        在 main.py 中通过 GUI 的"导出报告"按钮触发调用。
        
        Args:
            filename: 输出文件名，None 则自动生成
            
        Returns:
            保存的文件完整路径
        """
        # 自动生成带时间戳的文件名
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"report_{timestamp}.txt"
        
        filepath = os.path.join(self.output_dir, filename)
        
        with self._lock:
            history_copy = list(self.detection_history)
        
        # 写入文本报告
        with open(filepath, 'w', encoding='utf-8') as f:
            # ---- 报告标题 ----
            # 使用 "=" 分隔线突出标题
            f.write("=" * 50 + "\n")
            f.write("皮带传送带锚杆检测报告\n")
            f.write("=" * 50 + "\n\n")
            # 报告生成的时间戳
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # ---- 统计摘要 ----
            # 调用 get_detection_summary() 生成统计文本
            f.write(self.get_detection_summary() + "\n")
            
            # ---- 详细检测记录 ----
            # 使用 "-" 分隔线区分统计部分和详细记录部分
            f.write("-" * 50 + "\n")
            f.write("详细检测记录:\n")
            f.write("-" * 50 + "\n")
            
            # 遍历所有检测记录，enumerate 从 1 开始编号（更符合人类阅读习惯）
            for i, det in enumerate(history_copy, 1):
                f.write(f"\n检测 #{i}:\n")
                f.write(f"  时间: {det.timestamp}\n")
                # 帧ID 仅在存在时才写入（图片检测时 frame_id=0 也会显示）
                if det.frame_id is not None:
                    f.write(f"  帧ID: {det.frame_id}\n")
                f.write(f"  类别: {det.class_name}\n")
                # 置信度保留两位小数
                f.write(f"  置信度: {det.confidence:.2f}\n")
                # 位置：以 "(左上角x, 左上角y) - (右下角x, 右下角y)" 的格式展示
                f.write(f"  位置: ({det.bbox[0]}, {det.bbox[1]}) - ({det.bbox[2]}, {det.bbox[3]})\n")
        
        return filepath
    
    def clear_history(self):
        """
        清空历史记录
        
        同时清空检测历史列表和类别统计字典，将后处理器重置为初始状态。
        在 main.py 中当用户点击"清空检测记录"按钮并确认后调用。
        
        注意：此操作不可撤销，清空前应提醒用户确认（main.py 中已有确认对话框）。
        已导出的文件不受影响，仅清空内存中的记录。
        """
        with self._lock:
            self.detection_history.clear()
            self.statistics.clear()
    
    def get_recent_detections(self, count: int = 10) -> List[DetectionResult]:
        """
        获取最近的检测结果
        
        从检测历史的末尾取出指定数量的最新记录。可用于在 GUI 中实时滚动显示
        最近的检测事件，或在日志中输出最新的几条记录。
        
        Args:
            count: 需要获取的记录条数，默认 10 条。
                   传入 0 或负数则返回全部历史记录。
            
        Returns:
            DetectionResult 列表，按时间从旧到新排列（列表末尾为最新记录）
            如果历史记录不足 count 条，则返回全部可用记录
        """
        with self._lock:
            if count > 0:
                return list(self.detection_history[-count:])
            return list(self.detection_history)