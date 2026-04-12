# -*- coding: utf-8 -*-
"""
HTML报告生成模块
生成美化的HTML检测报告
"""
import os
from datetime import datetime


class ReportGenerator:
    """HTML报告生成器"""
    
    HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>锚杆检测报告</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        
        header {{
            text-align: center;
            border-bottom: 3px solid #0066cc;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        
        h1 {{
            font-size: 28px;
            color: #0066cc;
            margin-bottom: 10px;
        }}
        
        .report-meta {{
            font-size: 14px;
            color: #666;
        }}
        
        .report-meta p {{
            margin: 5px 0;
        }}
        
        section {{
            margin-bottom: 40px;
            padding: 20px;
            background-color: #f9f9f9;
            border-left: 4px solid #0066cc;
            border-radius: 4px;
        }}
        
        h2 {{
            font-size: 20px;
            color: #0066cc;
            margin-bottom: 15px;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 10px;
        }}
        
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        
        .summary-card {{
            background-color: white;
            padding: 15px;
            border-radius: 4px;
            border-left: 4px solid #0066cc;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        
        .summary-card .label {{
            font-size: 12px;
            color: #999;
            text-transform: uppercase;
            margin-bottom: 5px;
        }}
        
        .summary-card .value {{
            font-size: 24px;
            font-weight: bold;
            color: #0066cc;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            background-color: white;
        }}
        
        th {{
            background-color: #0066cc;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
        }}
        
        td {{
            padding: 12px;
            border-bottom: 1px solid #e0e0e0;
        }}
        
        tr:hover {{
            background-color: #f5f5f5;
        }}
        
        .progress-bar {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        
        .progress {{
            flex: 1;
            height: 20px;
            background-color: #e0e0e0;
            border-radius: 10px;
            overflow: hidden;
        }}
        
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #0066cc, #00a8ff);
        }}
        
        footer {{
            text-align: center;
            border-top: 1px solid #e0e0e0;
            padding-top: 20px;
            margin-top: 40px;
            color: #999;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>皮带传送带锚杆检测报告</h1>
            <div class="report-meta">
                <p><strong>生成时间:</strong> {generate_time}</p>
                <p><strong>检测总时长:</strong> {total_duration}</p>
            </div>
        </header>
        
        <section>
            <h2>📊 检测统计概览</h2>
            <div class="summary-grid">
                <div class="summary-card">
                    <div class="label">总检测数</div>
                    <div class="value">{total_detections}</div>
                </div>
                <div class="summary-card">
                    <div class="label">平均置信度</div>
                    <div class="value">{avg_confidence:.2f}</div>
                </div>
                <div class="summary-card">
                    <div class="label">主要类别</div>
                    <div class="value">{main_class}</div>
                </div>
            </div>
        </section>
        
        <section>
            <h2>📈 类别统计分析</h2>
            <table>
                <thead>
                    <tr>
                        <th>检测类别</th>
                        <th>检测数量</th>
                        <th>占比</th>
                        <th>可视化</th>
                    </tr>
                </thead>
                <tbody>
                    {class_stats_rows}
                </tbody>
            </table>
        </section>
        
        <section>
            <h2>📋 详细检测记录 (前100条)</h2>
            <table>
                <thead>
                    <tr>
                        <th>时间戳</th>
                        <th>帧ID</th>
                        <th>检测类别</th>
                        <th>置信度</th>
                        <th>位置</th>
                    </tr>
                </thead>
                <tbody>
                    {detail_records}
                </tbody>
            </table>
        </section>
        
        <footer>
            <p>此报告由皮带传送带锚杆检测系统自动生成</p>
            <p>© 2026 All Rights Reserved</p>
        </footer>
    </div>
</body>
</html>
"""
    
    def __init__(self, post_processor, logger=None):
        self.post_processor = post_processor
        self.logger = logger
    
    def generate_html_report(self, output_file=None):
        """生成HTML报告"""
        try:
            stats = self.post_processor.get_statistics()
            detections = self.post_processor.get_detection_history_copy()
            
            if not detections:
                if self.logger:
                    self.logger.warning("没有检测��据，无法生成报告")
                return None
            
            total_detections = len(detections)
            main_class = max(stats.items(), key=lambda x: x[1])[0] if stats else "未知"
            avg_confidence = sum(d.confidence for d in detections) / len(detections) if detections else 0
            generate_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            if detections:
                start_time = min(d.timestamp for d in detections)
                end_time = max(d.timestamp for d in detections)
                total_duration = f"{start_time} 至 {end_time}"
            else:
                total_duration = "无"
            
            class_stats_rows = self._generate_class_stats_rows(stats, total_detections)
            detail_records = self._generate_detail_records(detections)
            
            html_content = self.HTML_TEMPLATE.format(
                generate_time=generate_time,
                total_duration=total_duration,
                total_detections=total_detections,
                avg_confidence=avg_confidence,
                main_class=main_class,
                class_stats_rows=class_stats_rows,
                detail_records=detail_records
            )
            
            if output_file is None:
                output_dir = self.post_processor.output_dir
                os.makedirs(output_dir, exist_ok=True)
                output_file = os.path.join(
                    output_dir,
                    f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
                )
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            if self.logger:
                self.logger.info(f"HTML报告已生成: {output_file}")
            
            return output_file
        
        except Exception as e:
            if self.logger:
                self.logger.exception(f"生成HTML报告失败: {e}")
            raise
    
    def _generate_class_stats_rows(self, stats, total):
        """生成类别统计表格行"""
        rows = []
        for class_name, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / total * 100) if total > 0 else 0
            row = f"""
                <tr>
                    <td>{class_name}</td>
                    <td>{count}</td>
                    <td>{percentage:.2f}%</td>
                    <td>
                        <div class="progress-bar">
                            <div class="progress">
                                <div class="progress-fill" style="width: {percentage}%"></div>
                            </div>
                        </div>
                    </td>
                </tr>
            """
            rows.append(row)
        return "".join(rows) if rows else "<tr><td colspan='4'>暂无数据</td></tr>"
    
    def _generate_detail_records(self, detections, limit=100):
        """生成详细记录"""
        rows = []
        for det in detections[:limit]:
            row = f"""
                <tr>
                    <td>{det.timestamp}</td>
                    <td>{det.frame_id if det.frame_id is not None else '-'}</td>
                    <td>{det.class_name}</td>
                    <td>{det.confidence:.2f}</td>
                    <td>({det.bbox[0]},{det.bbox[1]},{det.bbox[2]},{det.bbox[3]})</td>
                </tr>
            """
            rows.append(row)
        return "".join(rows) if rows else "<tr><td colspan='5'>暂无数据</td></tr>"