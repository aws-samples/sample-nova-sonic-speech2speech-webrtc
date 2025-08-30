#!/usr/bin/env python3
"""
Audio Merger - 将多个音频片段合并为完整的WAV文件
用于将WebRTC原始音频和重采样后的音频分别合并成单个文件，方便播放和校验
"""

import os
import wave
import numpy as np
import logging
from typing import List, Tuple
import glob
from datetime import datetime

logger = logging.getLogger(__name__)

class AudioMerger:
    """音频合并器 - 将多个音频片段合并为完整的WAV文件"""
    
    def __init__(self, logs_dir: str = None):
        if logs_dir is None:
            # 默认使用相对于当前文件的logs目录
            self.logs_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
        else:
            self.logs_dir = logs_dir
            
        self.original_audio_dir = os.path.join(self.logs_dir, "original_audio")
        self.processed_audio_dir = os.path.join(self.logs_dir, "audio_data")
        self.merged_audio_dir = os.path.join(self.logs_dir, "merged_audio")
        
        # 确保合并音频目录存在
        os.makedirs(self.merged_audio_dir, exist_ok=True)
        
    def get_audio_files(self, directory: str, pattern: str = "*.wav") -> List[str]:
        """获取目录中的音频文件列表，按文件名排序"""
        if not os.path.exists(directory):
            logger.warning(f"目录不存在: {directory}")
            return []
            
        files = glob.glob(os.path.join(directory, pattern))
        # 按文件名排序，确保时间顺序正确
        files.sort()
        return files
        
    def read_wav_file(self, filepath: str) -> Tuple[np.ndarray, int]:
        """读取WAV文件，返回音频数据和采样率"""
        try:
            with wave.open(filepath, 'rb') as wav_file:
                # 获取音频参数
                frames = wav_file.getnframes()
                sample_rate = wav_file.getframerate()
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                
                # 读取音频数据
                audio_data = wav_file.readframes(frames)
                
                # 转换为numpy数组
                if sample_width == 1:
                    # 8位音频
                    audio_array = np.frombuffer(audio_data, dtype=np.uint8)
                    audio_array = audio_array.astype(np.float32) / 127.5 - 1.0
                elif sample_width == 2:
                    # 16位音频
                    audio_array = np.frombuffer(audio_data, dtype=np.int16)
                    audio_array = audio_array.astype(np.float32) / 32767.0
                elif sample_width == 4:
                    # 32位音频
                    audio_array = np.frombuffer(audio_data, dtype=np.int32)
                    audio_array = audio_array.astype(np.float32) / 2147483647.0
                else:
                    raise ValueError(f"不支持的采样位深: {sample_width}")
                
                # 处理多声道音频（转换为单声道）
                if channels > 1:
                    audio_array = audio_array.reshape(-1, channels)
                    audio_array = np.mean(audio_array, axis=1)
                
                return audio_array, sample_rate
                
        except Exception as e:
            logger.error(f"读取WAV文件失败 {filepath}: {e}")
            return None, None
            
    def write_wav_file(self, filepath: str, audio_data: np.ndarray, sample_rate: int):
        """将音频数据写入WAV文件"""
        try:
            # 确保音频数据在有效范围内
            audio_data = np.clip(audio_data, -1.0, 1.0)
            
            # 转换为16位整数
            audio_int16 = (audio_data * 32767).astype(np.int16)
            
            with wave.open(filepath, 'wb') as wav_file:
                wav_file.setnchannels(1)  # 单声道
                wav_file.setsampwidth(2)  # 16位
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(audio_int16.tobytes())
                
            logger.info(f"✅ 成功写入WAV文件: {filepath}")
            logger.info(f"   采样率: {sample_rate}Hz, 时长: {len(audio_data)/sample_rate:.2f}秒")
            
        except Exception as e:
            logger.error(f"写入WAV文件失败 {filepath}: {e}")
            
    def merge_audio_files(self, input_files: List[str], output_file: str, 
                         expected_sample_rate: int = None) -> bool:
        """合并多个音频文件为一个WAV文件"""
        if not input_files:
            logger.warning("没有找到要合并的音频文件")
            return False
            
        logger.info(f"🔄 开始合并 {len(input_files)} 个音频文件...")
        logger.info(f"   输出文件: {output_file}")
        
        merged_audio = []
        actual_sample_rate = None
        total_duration = 0
        
        for i, filepath in enumerate(input_files):
            audio_data, sample_rate = self.read_wav_file(filepath)
            
            if audio_data is None:
                logger.warning(f"跳过无效文件: {filepath}")
                continue
                
            # 检查采样率一致性
            if actual_sample_rate is None:
                actual_sample_rate = sample_rate
            elif actual_sample_rate != sample_rate:
                logger.warning(f"采样率不一致: {filepath} ({sample_rate}Hz vs {actual_sample_rate}Hz)")
                # 简单重采样（线性插值）
                if sample_rate != actual_sample_rate:
                    ratio = actual_sample_rate / sample_rate
                    new_length = int(len(audio_data) * ratio)
                    old_indices = np.linspace(0, len(audio_data) - 1, len(audio_data))
                    new_indices = np.linspace(0, len(audio_data) - 1, new_length)
                    audio_data = np.interp(new_indices, old_indices, audio_data)
                    
            merged_audio.append(audio_data)
            total_duration += len(audio_data) / actual_sample_rate
            
            # 每处理50个文件打印一次进度
            if (i + 1) % 50 == 0:
                logger.info(f"   已处理: {i + 1}/{len(input_files)} 个文件")
        
        if not merged_audio:
            logger.error("没有有效的音频数据可以合并")
            return False
            
        # 合并所有音频数据
        logger.info("🔗 正在合并音频数据...")
        final_audio = np.concatenate(merged_audio)
        
        # 验证期望的采样率
        if expected_sample_rate and actual_sample_rate != expected_sample_rate:
            logger.warning(f"采样率不匹配: 期望 {expected_sample_rate}Hz, 实际 {actual_sample_rate}Hz")
        
        # 写入合并后的文件
        self.write_wav_file(output_file, final_audio, actual_sample_rate)
        
        logger.info(f"✅ 音频合并完成!")
        logger.info(f"   合并文件数: {len(merged_audio)}")
        logger.info(f"   总时长: {total_duration:.2f}秒")
        logger.info(f"   采样率: {actual_sample_rate}Hz")
        logger.info(f"   总样本数: {len(final_audio)}")
        
        return True
        
    def merge_original_audio(self, session_prefix: str = None) -> str:
        """合并原始WebRTC音频文件 (48kHz)"""
        logger.info("🎵 开始合并原始WebRTC音频文件...")
        
        # 获取原始音频文件
        if session_prefix:
            pattern = f"original_{session_prefix}_*.wav"
        else:
            pattern = "original_*.wav"
            
        input_files = self.get_audio_files(self.original_audio_dir, pattern)
        
        if not input_files:
            logger.warning(f"未找到原始音频文件: {pattern}")
            return None
            
        # 生成输出文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if session_prefix:
            output_filename = f"merged_original_{session_prefix}.wav"
        else:
            output_filename = f"merged_original_{timestamp}.wav"
            
        output_file = os.path.join(self.merged_audio_dir, output_filename)
        
        # 合并文件
        success = self.merge_audio_files(input_files, output_file, expected_sample_rate=48000)
        
        if success:
            logger.info(f"✅ 原始音频合并完成: {output_file}")
            return output_file
        else:
            logger.error("❌ 原始音频合并失败")
            return None
            
    def merge_processed_audio(self, session_prefix: str = None) -> str:
        """合并处理后的音频文件 (16kHz)"""
        logger.info("🎵 开始合并处理后音频文件...")
        
        # 获取处理后音频文件
        if session_prefix:
            pattern = f"audio_{session_prefix}_*.wav"
        else:
            pattern = "audio_*.wav"
            
        input_files = self.get_audio_files(self.processed_audio_dir, pattern)
        
        if not input_files:
            logger.warning(f"未找到处理后音频文件: {pattern}")
            return None
            
        # 生成输出文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if session_prefix:
            output_filename = f"merged_processed_{session_prefix}.wav"
        else:
            output_filename = f"merged_processed_{timestamp}.wav"
            
        output_file = os.path.join(self.merged_audio_dir, output_filename)
        
        # 合并文件
        success = self.merge_audio_files(input_files, output_file, expected_sample_rate=16000)
        
        if success:
            logger.info(f"✅ 处理后音频合并完成: {output_file}")
            return output_file
        else:
            logger.error("❌ 处理后音频合并失败")
            return None
            
    def merge_all_audio(self, session_prefix: str = None) -> Tuple[str, str]:
        """合并所有音频文件（原始和处理后）"""
        logger.info("🎵 开始合并所有音频文件...")
        
        original_file = self.merge_original_audio(session_prefix)
        processed_file = self.merge_processed_audio(session_prefix)
        
        return original_file, processed_file
        
    def get_audio_info(self, directory: str) -> dict:
        """获取音频目录的统计信息"""
        files = self.get_audio_files(directory)
        
        if not files:
            return {"file_count": 0, "total_duration": 0, "sample_rate": None}
            
        total_duration = 0
        sample_rates = set()
        
        for filepath in files[:10]:  # 只检查前10个文件以获取基本信息
            audio_data, sample_rate = self.read_wav_file(filepath)
            if audio_data is not None:
                total_duration += len(audio_data) / sample_rate
                sample_rates.add(sample_rate)
                
        # 估算总时长（基于前10个文件的平均时长）
        if total_duration > 0:
            avg_duration = total_duration / min(10, len(files))
            estimated_total = avg_duration * len(files)
        else:
            estimated_total = 0
            
        return {
            "file_count": len(files),
            "estimated_total_duration": estimated_total,
            "sample_rates": list(sample_rates)
        }

def main():
    """主函数 - 命令行使用示例"""
    import argparse
    
    parser = argparse.ArgumentParser(description="合并音频文件")
    parser.add_argument("--session", help="会话前缀 (例如: 20250824_001403)")
    parser.add_argument("--original-only", action="store_true", help="只合并原始音频")
    parser.add_argument("--processed-only", action="store_true", help="只合并处理后音频")
    parser.add_argument("--info", action="store_true", help="显示音频目录信息")
    
    args = parser.parse_args()
    
    # 设置日志
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    merger = AudioMerger()
    
    if args.info:
        # 显示音频目录信息
        print("\n📊 音频目录统计信息:")
        
        original_info = merger.get_audio_info(merger.original_audio_dir)
        print(f"\n🎵 原始音频 (logs/original_audio/):")
        print(f"   文件数量: {original_info['file_count']}")
        print(f"   估计总时长: {original_info['estimated_total_duration']:.2f}秒")
        print(f"   采样率: {original_info['sample_rates']}")
        
        processed_info = merger.get_audio_info(merger.processed_audio_dir)
        print(f"\n🎵 处理后音频 (logs/audio_data/):")
        print(f"   文件数量: {processed_info['file_count']}")
        print(f"   估计总时长: {processed_info['estimated_total_duration']:.2f}秒")
        print(f"   采样率: {processed_info['sample_rates']}")
        
        return
    
    if args.original_only:
        merger.merge_original_audio(args.session)
    elif args.processed_only:
        merger.merge_processed_audio(args.session)
    else:
        merger.merge_all_audio(args.session)

if __name__ == "__main__":
    main()