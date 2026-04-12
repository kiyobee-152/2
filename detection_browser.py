# -*- coding: utf-8 -*-
"""
检测结果浏览器模块
提供历史检测结果的查看和筛选功能
"""
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, 
                             QTableWidgetItem, QPushButton, QLineEdit, QComboBox, 
                             QLabel, QSpinBox, QMessageBox, QFileDialog)
from PyQt5.QtCore import Qt
from datetime import datetime
import json
import os


class DetectionBrowser(QDialog):
    """检测结果浏览器窗口"""
    
    def __init__(self, post_processor, logger=None, parent=None):
        super().__init__(parent)
        self.post_processor = post_processor
        self.logger = logger
        
        self.setWindowTitle("检测结果浏览器")
        self.setGeometry(50, 50, 1400, 700)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Window)
        
        self.init_ui()
        self.load_data()
    
    def init_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout()
        
        # 搜索和筛选栏
        filter_layout = QHBoxLayout()
        
        class_label = QLabel("类别:")
        self.class_combo = QComboBox()
        self.class_combo.addItem("所有类别")
        self.class_combo.currentIndexChanged.connect(self.filter_data)
        filter_layout.addWidget(class_label)
        filter_layout.addWidget(self.class_combo)
        
        conf_label = QLabel("最小置信度:")
        self.conf_spin = QSpinBox()
        self.conf_spin.setRange(0, 100)
        self.conf_spin.setValue(0)
        self.conf_spin.setSuffix("%")
        self.conf_spin.valueChanged.connect(self.filter_data)
        filter_layout.addWidget(conf_label)
        filter_layout.addWidget(self.conf_spin)
        
        search_label = QLabel("搜索帧ID:")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入帧ID...")
        self.search_input.textChanged.connect(self.filter_data)
        filter_layout.addWidget(search_label)
        filter_layout.addWidget(self.search_input)
        
        filter_layout.addStretch()
        
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.load_data)
        export_btn = QPushButton("导出选中")
        export_btn.clicked.connect(self.export_selected)
        
        filter_layout.addWidget(refresh_btn)
        filter_layout.addWidget(export_btn)
        
        # 数据表格
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "时间戳", "帧ID", "类别", "置信度", "位置", "操作"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        
        # 统计信息
        self.stats_label = QLabel()
        
        main_layout.addLayout(filter_layout)
        main_layout.addWidget(self.table)
        main_layout.addWidget(self.stats_label)
        
        self.setLayout(main_layout)
    
    def load_data(self):
        """加载所有检测数据"""
        try:
            detections = self.post_processor.get_detection_history_copy()
            
            classes = set([d.class_name for d in detections])
            self.class_combo.blockSignals(True)
            current_class = self.class_combo.currentText()
            self.class_combo.clear()
            self.class_combo.addItem("所有类别")
            self.class_combo.addItems(sorted(classes))
            
            if current_class != "所有类别" and self.class_combo.findText(current_class) >= 0:
                self.class_combo.setCurrentText(current_class)
            self.class_combo.blockSignals(False)
            
            self.all_detections = detections
            self.filter_data()
            
            if self.logger:
                self.logger.info(f"浏览器加载了 {len(detections)} 条检测记录")
        
        except Exception as e:
            if self.logger:
                self.logger.exception(f"加载数据失败: {e}")
            QMessageBox.warning(self, "错误", f"加载数据失败: {str(e)}")
    
    def filter_data(self):
        """根据筛选条件过滤数据"""
        try:
            selected_class = self.class_combo.currentText()
            min_confidence = self.conf_spin.value() / 100.0
            search_frame_id = self.search_input.text().strip()
            
            filtered = []
            for det in self.all_detections:
                if selected_class != "所有类别" and det.class_name != selected_class:
                    continue
                
                if det.confidence < min_confidence:
                    continue
                
                if search_frame_id and str(det.frame_id) != search_frame_id:
                    continue
                
                filtered.append(det)
            
            self.update_table(filtered)
            
            total = len(self.all_detections)
            shown = len(filtered)
            self.stats_label.setText(f"显示 {shown}/{total} 条记录")
        
        except Exception as e:
            if self.logger:
                self.logger.exception(f"筛选数据失败: {e}")
    
    def update_table(self, detections):
        """更新表格显示"""
        self.table.setRowCount(len(detections))
        
        for row, det in enumerate(detections):
            self.table.setItem(row, 0, QTableWidgetItem(det.timestamp))
            frame_id = str(det.frame_id) if det.frame_id is not None else "-"
            self.table.setItem(row, 1, QTableWidgetItem(frame_id))
            self.table.setItem(row, 2, QTableWidgetItem(det.class_name))
            conf_text = f"{det.confidence:.2f}"
            self.table.setItem(row, 3, QTableWidgetItem(conf_text))
            bbox_text = f"({det.bbox[0]},{det.bbox[1]},{det.bbox[2]},{det.bbox[3]})"
            self.table.setItem(row, 4, QTableWidgetItem(bbox_text))
            
            save_btn = QPushButton("保存")
            save_btn.clicked.connect(lambda checked, r=row: self.save_detection(r))
            self.table.setCellWidget(row, 5, save_btn)
        
        self.table.resizeColumnsToContents()
    
    def export_selected(self):
        """导出选中的记录"""
        try:
            selected = self.table.selectedIndexes()
            if not selected:
                QMessageBox.warning(self, "提示", "请先选择要导出的记录")
                return
            
            rows = set([idx.row() for idx in selected])
            
            export_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
            if not export_dir:
                return
            
            export_data = []
            for row in sorted(rows):
                timestamp = self.table.item(row, 0).text()
                
                for det in self.all_detections:
                    if det.timestamp == timestamp:
                        export_data.append(det.to_dict())
                        break
            
            export_file = os.path.join(export_dir, f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(export_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            QMessageBox.information(self, "成功", f"已导出 {len(export_data)} 条记录到:\n{export_file}")
            if self.logger:
                self.logger.info(f"导出了 {len(export_data)} 条检测记录到 {export_file}")
        
        except Exception as e:
            if self.logger:
                self.logger.exception(f"导出失败: {e}")
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")
    
    def save_detection(self, row):
        """保存单条检测记录"""
        try:
            timestamp = self.table.item(row, 0).text()
            
            export_dir = QFileDialog.getExistingDirectory(self, "选择保存目录")
            if not export_dir:
                return
            
            for det in self.all_detections:
                if det.timestamp == timestamp:
                    save_file = os.path.join(export_dir, f"detection_{det.class_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
                    with open(save_file, 'w', encoding='utf-8') as f:
                        json.dump(det.to_dict(), f, ensure_ascii=False, indent=2)
                    
                    QMessageBox.information(self, "成功", f"已保存到:\n{save_file}")
                    break
        
        except Exception as e:
            if self.logger:
                self.logger.exception(f"保存失败: {e}")
            QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")