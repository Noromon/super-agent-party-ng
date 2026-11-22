# -*- coding: utf-8 -*-
"""S299：图像绘制（自 server.py 逐字搬移）：桌面网格坐标/动作反馈轨迹/缩放适配。

server 侧 re-export 原函数名供流式引擎引用；本模块零 server 依赖。
"""
import re

from PIL import Image, ImageDraw


def draw_grid_on_image(image: Image.Image, grid_spacing: int = 10) -> Image.Image:
    """
    在图片上绘制网格和千分比坐标标签
    grid_spacing: 每隔多少百分比画一根线，默认 10 (即 10x10 的网格)
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    
    # 颜色设置 (半透明红色或亮绿色，视情况而定)
    line_color = (255, 0, 0, 128)  # 红色线
    text_color = (255, 0, 0, 255)
    
    # 绘制垂直线 (百分比 0-100，但标签显示为千分比 0-1000‰)
    for x_pc in range(0, 101, grid_spacing):
        x = int(width * (x_pc / 100.0))
        # 确保不超出边界
        x = min(x, width - 1)
        draw.line([(x, 0), (x, height)], fill=line_color, width=1)
        x_permille = x_pc
        draw.text((x + 2, 5), f"{x_permille}%", fill=text_color)

    # 绘制水平线
    for y_pc in range(0, 101, grid_spacing):
        y = int(height * (y_pc / 100.0))
        y = min(y, height - 1)
        draw.line([(0, y), (width, y)], fill=line_color, width=1)
        y_permille = y_pc
        draw.text((5, y + 2), f"{y_permille}%", fill=text_color)
        
    return image

def draw_action_feedback(image: Image.Image, action_str: str) -> Image.Image:
    """
    解析返回结果字符串，并在图像上绘制动作反馈轨迹。
    （已针对红色网格优化，全面移除红色，使用高对比度的青/蓝/绿/黄色）
    """
    # 强制将原始图像转换为 RGBA，以便使用半透明色彩
    image = image.convert("RGBA")
    
    # 创建一个与原图同尺寸的透明涂层
    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = image.size
    
    def to_px(tx, ty):
        return int(float(tx) * w / 1000), int(float(ty) * h / 1000)

    # 1. 匹配 MOVE(x,y) -> 画个白色小圆点带黑边
    move_match = re.search(r"\[LAST_ACTION: MOVE\((\d+\.?\d*),(\d+\.?\d*)\)\]", action_str)
    if move_match:
        x, y = move_match.groups()
        px, py = to_px(x, y)
        r = 6
        draw.ellipse([px-r, py-r, px+r, py+r], fill=(255, 255, 255, 200), outline=(0, 0, 0, 255), width=1)

    # 2. 匹配 CLICK(x,y) -> 画个青色(Cyan)半透明十字靶心 (对比红色网格极佳)
    click_match = re.search(r"\[LAST_ACTION: CLICK\((\d+\.?\d*),(\d+\.?\d*)\)\]", action_str)
    if click_match:
        x, y = click_match.groups()
        px, py = to_px(x, y)
        r = 12
        # 青色底圈
        draw.ellipse([px-r, py-r, px+r, py+r], fill=(0, 255, 255, 150), outline=(255, 255, 255, 255), width=2)
        # 白色十字
        draw.line([px-r-5, py, px+r+5, py], fill=(255, 255, 255, 255), width=2)
        draw.line([px, py-r-5, px, py+r+5], fill=(255, 255, 255, 255), width=2)

    # 3. 匹配 DOUBLE_CLICK(x,y) -> 画个蓝色(Blue)双圈靶心
    dclick_match = re.search(r"\[LAST_ACTION: DOUBLE_CLICK\((\d+\.?\d*),(\d+\.?\d*)\)\]", action_str)
    if dclick_match:
        x, y = dclick_match.groups()
        px, py = to_px(x, y)
        r = 14
        # 蓝色底圈
        draw.ellipse([px-r, py-r, px+r, py+r], fill=(0, 100, 255, 150), outline=(255, 255, 255, 255), width=2)
        # 内层白圈
        draw.ellipse([px-(r-4), py-(r-4), px+(r-4), py+(r-4)], outline=(255, 255, 255, 255), width=1)

    # 4. 匹配 DRAG(x1,y1,x2,y2) -> 绿色轨迹线，绿色起点，黄色终点
    drag_match = re.search(r"\[LAST_ACTION: DRAG\((\d+\.?\d*),(\d+\.?\d*),(\d+\.?\d*),(\d+\.?\d*)\)\]", action_str)
    if drag_match:
        x1, y1, x2, y2 = drag_match.groups()
        p1 = to_px(x1, y1)
        p2 = to_px(x2, y2)
        
        # 绿色带透明度的连接线
        draw.line([p1, p2], fill=(0, 255, 0, 200), width=4)
        
        # 绿色起点圆
        draw.ellipse([p1[0]-6, p1[1]-6, p1[0]+6, p1[1]+6], fill=(0, 255, 0, 255), outline=(255,255,255,255), width=1)
        
        # 黄色终点靶心 (黄色在网格上也很显眼)
        r_end = 8
        draw.ellipse([p2[0]-r_end, p2[1]-r_end, p2[0]+r_end, p2[1]+r_end], fill=(255, 215, 0, 180), outline=(255,255,255,255), width=2)

    # 合并图层，转回 RGB (防 JPG 格式不支持 Alpha 通道)
    combined = Image.alpha_composite(image, overlay)
    return combined.convert("RGB")

def scale_to_fit(width: int, height: int, max_w: int = 1920, max_h: int = 1080) -> tuple[int, int]:
    """计算等比例缩放后的尺寸"""
    # 计算宽和高的缩放比例
    scale_w = max_w / width
    scale_h = max_h / height
    
    # 取较小的那个缩放比例，确保长宽都不超过限制
    scale = min(scale_w, scale_h, 1.0) # 如果原图比 1920x1080 小，则不放大(1.0)
    
    new_width = int(width * scale)
    new_height = int(height * scale)
    return new_width, new_height
