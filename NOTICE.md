# NOTICE · 素材版权声明

本仓库（Source2Voice）**只包含脚本与文档，不包含任何游戏资源**。

## 游戏语音资源

流程中提取的音频（`.wav` / `.mp3`）与官方台词文本，版权归 **Valve Corporation** 所有，
受 Dota 2 最终用户许可协议（EULA）约束。

- 本项目提供的是**处理工具与工作流说明**，使用者需自行在本地游戏安装中提取资源。
- **请勿**将提取出的音频用于商业分发或二次分发。
- 训练出的模型权重同样应遵守原素材的授权条款。

## 第三方组件

| 组件 | 用途 | 许可 |
|---|---|---|
| [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice) | TTS 基座模型 | Apache-2.0 |
| [Qwen/Qwen3](https://github.com/QwenLM/Qwen3) | LLM 底座（0.6B） | Apache-2.0 |
| [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) | ASR | MIT |
| [openai/whisper](https://github.com/openai/whisper) | ASR 参考实现 | MIT |
| [FunAudioLLM/CosyVoice](https://github.com/FunAudioLLM/CosyVoice) | campplus 说话人验证 | Apache-2.0 |
| [huggingface_hub](https://github.com/huggingface/huggingface_hub) | 模型发布 | Apache-2.0 |
| [webdataset](https://github.com/webdataset/webdataset) | 训练数据分片 | Apache-2.0 |
| [pypinyin](https://github.com/mozillazg/python-pinyin) | 拼音匹配 | MIT |
| [opencc-python-reimplemented](https://github.com/BYVoid/OpenCC) | 繁简转换 | Apache-2.0 |

## 本仓库代码

MIT 许可，见 [LICENSE](LICENSE)。
