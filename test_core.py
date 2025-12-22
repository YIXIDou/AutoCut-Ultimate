from scenedetect import open_video, SceneManager
from scenedetect.detectors import AdaptiveDetector
import cv2  # 必须引入 cv2 来强制获取帧数
import subprocess
import os

# ==================== 1. 核心工具类：支持中断和进度的视频包装器 ====================
class InterruptibleVideo:
    def __init__(self, video, path, stop_event=None, progress_callback=None):
        self._video = video
        self._path = path # 保存路径以便备用
        self._stop_event = stop_event
        self._callback = progress_callback
        
        # 属性转发
        self.frame_rate = video.frame_rate
        self.base_timecode = video.base_timecode
        
        # --- 核心修复：强力获取总帧数 ---
        self._total_frames = 0
        
        # 尝试方法 A: scenedetect 自带
        if hasattr(video, "count_frames"):
            self._total_frames = video.count_frames()
        elif hasattr(video, "frame_count"):
            self._total_frames = video.frame_count
            
        # 尝试方法 B: 如果拿到的是0，用 OpenCV 物理读取
        if self._total_frames <= 0:
            print("[Debug] scenedetect 未返回帧数，尝试使用 OpenCV 读取...")
            try:
                temp_cap = cv2.VideoCapture(path)
                self._total_frames = int(temp_cap.get(cv2.CAP_PROP_FRAME_COUNT))
                temp_cap.release()
                print(f"[Debug] OpenCV 获取总帧数: {self._total_frames}")
            except Exception as e:
                print(f"[Debug] 获取帧数失败: {e}")

        # 如果还是 0，设为 1 防止除以零报错
        if self._total_frames <= 0:
            self._total_frames = 1
            
        self._current_frame = 0

    def read(self):
        # 1. 检查停止
        if self._stop_event and self._stop_event.is_set():
            return False 
        
        # 2. 读取
        frame = self._video.read()
        
        # 3. 汇报进度
        if frame is not False and frame is not None:
            self._current_frame += 1
            
            # 每 24 帧(约1秒)汇报一次
            if self._current_frame % 24 == 0:
                # 无论是否有 callback，先在终端打印一下证明在跑
                # print(f"\r[Debug] 分析中: {self._current_frame}/{self._total_frames}", end="")
                
                if self._callback:
                    # 即使 total_frames 是假的(1)，也要回调，确保 UI 不死
                    progress = self._current_frame / self._total_frames
                    # 限制最大 1.0
                    if progress > 1.0: progress = 1.0
                    self._callback(progress)
        
        return frame

    def __getattr__(self, name):
        return getattr(self._video, name)


# ==================== 2. 核心算法函数 ====================

def find_scenes_optimized(video_path, threshold, min_len, progress_callback=None, stop_event=None):
    print(f"正在分析视频: {video_path} ...")
    
    # 打开视频
    original_video = open_video(video_path)
    
    # 包装视频 (传入 video_path 用于备用方案)
    video = InterruptibleVideo(original_video, video_path, stop_event, progress_callback)
    
    fps = video.frame_rate
    
    scene_manager = SceneManager()
    scene_manager.add_detector(
        AdaptiveDetector(adaptive_threshold=threshold, min_scene_len=min_len)
    )
    
    # 开始检测
    scene_manager.detect_scenes(video, show_progress=False)
    print("\n[Debug] 分析循环结束，正在整理切点...")
    
    scene_list = scene_manager.get_scene_list()
    
    processed_scenes = []
    for scene in scene_list:
        start_time = scene[0]
        end_time = scene[1]
        start_frame = start_time.get_frames()
        
        if start_frame == 0:
            continue
            
        processed_scenes.append((start_frame, end_time))
        
    return processed_scenes, fps


# ==================== 3. 辅助函数：时间码转换 (Pr风格) ====================
def frames_to_timecode_premiere(frame_num, fps):
    fps_int = int(round(fps))
    frame_num = int(frame_num)
    
    ff = frame_num % fps_int
    total_seconds = frame_num // fps_int
    
    ss = total_seconds % 60
    mm = (total_seconds // 60) % 60
    hh = (total_seconds // 60) // 60
    
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


# ==================== 4. 导出函数 (支持选区导出) ====================
def export_video_clips(video_path, clips, output_dir, base_name="clip", progress_callback=None, stop_event=None):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    cap = open_video(video_path)
    fps = cap.frame_rate
    
    total_clips = len(clips)
    success_count = 0
    
    for i, (start, end) in enumerate(clips):
        if stop_event and stop_event.is_set():
            break
            
        start_time = start / fps
        duration = (end - start) / fps
        
        output_filename = f"{base_name}_{i+1:03d}.mp4"
        output_path = os.path.join(output_dir, output_filename)
        
        if progress_callback:
            progress_callback((i + 1) / total_clips)
        
        print(f"Exporting {i+1}/{total_clips}: {output_filename}")

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_time:.3f}",
            "-i", video_path,
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-c:a", "aac",
            output_path
        ]
        
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        success_count += 1
        
    return success_count

# ==================== 5. 独立测试入口 ====================
if __name__ == "__main__":
    print(">>> 独立测试模式 <<<")
    # 这里你可以填死一个路径来快速测试，不用每次输入
    test_video = input("请输入视频路径: ").strip()
    if test_video and os.path.exists(test_video):
        def test_callback(p):
            print(f"\r进度: {p*100:.1f}%", end="")
            
        print("开始测试分析...")
        res = find_scenes_optimized(test_video, 5.0, 12, progress_callback=test_callback)
        print("\n完成。")