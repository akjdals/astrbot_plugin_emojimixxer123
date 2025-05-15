from typing import Optional, List, Dict, Any
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import httpx
import emoji


@register("emojimix", "akjdasl", "Emoji合成插件", "1.1", "https://github.com/akjdals/emojimix")
class EmojiMixPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config = self._load_config()
        self._validate_config()

    def _load_config(self) -> dict:
        """加载并合并默认配置与用户配置"""
        default_config: Dict[str, Any] = {
            "emoji_size": 128,
            "twemoji_cdn": "https://cdn.jsdelivr.net/npm/twemoji@latest/assets/svg/",
            "date_codes": [
                "20240204", "20250130", "20241023", "20241021", "20240715",
                "20240610", "20240530", "20240214", "20240206", "20231128",
                "20231113", "20230821", "20230818", "20230803", "20230426",
                "20230421", "20230418", "20230405", "20230301", "20230221",
                "20230216", "20230127", "20230126", "20221107", "20221101",
                "20220823", "20220815", "20220506", "20220406", "20220203",
                "20220110", "20211115", "20210831", "20210521", "20210218",
                "20201001"
            ],
            "base_url_template": "https://www.gstatic.com/android/keyboard/emojikitchen/{date_code}/{hex1}/{hex1}_{hex2}.png",
            "request_timeout": 3.0,
            "max_emoji_length": 2  # 限制最多处理2个Emoji
        }
        
        return default_config

    def _validate_config(self) -> None:
        """验证配置有效性（关键参数检查）"""
        required_keys = ["twemoji_cdn", "base_url_template", "date_codes"]
        for key in required_keys:
            if key not in self.config:
                raise ValueError(f"配置缺失关键参数: {key}")
        
        if not isinstance(self.config["date_codes"], list):
            raise TypeError("date_codes必须为列表类型")

    async def download_emoji(self, emoji_char: str) -> Optional[bytes]:
        """
        下载单个Emoji的SVG文件
        :param emoji_char: 目标Emoji字符（如"😊"）
        :return: SVG字节数据或None（失败时）
        """
        try:
            # 处理多码点Emoji（如国旗由2个区域指示符组成）
            hex_codes = "-".join(f"{ord(c):x}" for c in emoji_char)
            url = f"{self.config['twemoji_cdn']}{hex_codes}.svg"
            
            async with httpx.AsyncClient(timeout=self.config["request_timeout"]) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    logger.debug(f"成功下载Emoji {emoji_char} 的SVG文件")
                    return resp.content
                logger.warning(f"下载失败: {url} (HTTP {resp.status_code})")
        except Exception as e:
            logger.error(f"下载Emoji {emoji_char} 时发生异常: {str(e)}")
        return None

    def _get_emoji_hex_code(self, emoji_char: str) -> Optional[str]:
        """
        将Emoji转换为Emoji Kitchen所需的十六进制代码格式
        :param emoji_char: 目标Emoji字符
        :return: 十六进制代码字符串（如"u1f60a"或"u1f1e8-u1f1f3"）
        """
        try:
            filtered_chars = [c for c in emoji_char if c not in ("\ufe0e", "\ufe0f")]
            return "-".join(f"u{ord(c):x}" for c in filtered_chars)
        except Exception as e:
            logger.error(f"转换Emoji {emoji_char} 到十六进制时出错: {e}")
            return None

    async def _find_mixed_emoji_url(self, emoji1: str, emoji2: str) -> Optional[str]:
        """
        查找Emoji Kitchen混合图片URL（优化遍历逻辑）
        :param emoji1: 第一个Emoji
        :param emoji2: 第二个Emoji
        :return: 有效的混合图片URL或None
        """
        emoji1_hex = self._get_emoji_hex_code(emoji1)
        emoji2_hex = self._get_emoji_hex_code(emoji2)

        if not emoji1_hex or not emoji2_hex:
            logger.warning(f"无法获取{emoji1}或{emoji2}的有效十六进制代码")
            return None

        logger.info(f"尝试混合: {emoji1} ({emoji1_hex}) + {emoji2} ({emoji2_hex})")
        async with httpx.AsyncClient(timeout=self.config["request_timeout"]) as client:
            for date_code in self.config["date_codes"]:
                # 优先检查原始顺序（hex1_hex2）
                url_candidates = [
                    self.config["base_url_template"].format(
                        date_code=date_code, hex1=emoji1_hex, hex2=emoji2_hex
                    )
                ]
                # 如果Emoji不同，添加反向顺序（hex2_hex1）
                if emoji1 != emoji2:
                    url_candidates.append(
                        self.config["base_url_template"].format(
                            date_code=date_code, hex1=emoji2_hex, hex2=emoji1_hex
                        )
                    )

                for url in url_candidates:
                    try:
                        resp = await client.head(url, follow_redirects=True)
                        if resp.status_code == 200:
                            logger.info(f"找到有效混合URL: {url}")
                            return url
                        logger.debug(f"URL {url} 不存在（状态码{resp.status_code}）")
                    except httpx.RequestError as e:
                        logger.debug(f"检查URL {url} 时网络出错: {str(e)}")

        logger.info(f"未找到{emoji1}和{emoji2}的混合Emoji")
        return None

    def _extract_valid_emojis(self, text: str) -> List[str]:
        """
        提取文本中有效的Emoji（过滤不完整/无效的Emoji）
        :param text: 输入文本
        :return: 有效Emoji列表（最多2个）
        """
        try:
            emoji_entries = emoji.emoji_list(text)
            # 过滤掉非Emoji字符（如变体选择符）并去重
            valid_emojis = list({
                entry["emoji"] for entry in emoji_entries
                if emoji.is_emoji(entry["emoji"])  # 二次验证Emoji有效性
            })
            # 限制最多返回2个Emoji（根据配置）
            return valid_emojis[:self.config["max_emoji_length"]]
        except Exception as e:
            logger.error(f"提取Emoji时发生异常: {e}")
            return []

    async def _process_mix_request(self, event: AstrMessageEvent, emojis: List[str]) -> MessageEventResult:
        """
        统一处理Emoji混合请求（封装核心逻辑）
        :param event: 消息事件
        :param emojis: 提取到的有效Emoji列表
        :return: 消息结果
        """
        if len(emojis) != 2:
            return event.plain_result(
                "🤔 请提供恰好两个不同的Emoji来合成\n"
                "示例: `/emojimix 😊🐶` 或直接发送两个Emoji"
            )

        emoji1, emoji2 = emojis
        if emoji1 == emoji2:
            return event.plain_result("😅 两个Emoji不能相同哦~")

        mix_url = await self._find_mixed_emoji_url(emoji1, emoji2)
        if mix_url:
            return event.image_result(mix_url)
        return event.plain_result(
            f"😟 抱歉，未找到{emoji1}和{emoji2}的混合Emoji\n"
            "可能原因: 这对组合不存在 或 输入的不是标准Emoji"
        )

    @filter.command("emojimix", aliases=["合成表情"])
    async def emoji_mix_handler(self, event: AstrMessageEvent) -> Optional[MessageEventResult]:
        """处理/emojimix命令（输入验证优化）"""
        input_text = event.message_str.strip()
        emojis = self._extract_valid_emojis(input_text)
        return await self._process_mix_request(event, emojis)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_double_emoji_message(self, event: AstrMessageEvent) -> None:
        """自动检测双Emoji消息（增加触发阈值防止误判）"""
        message_text = event.message_str.strip()
        # 简单阈值：消息长度不超过10字符且仅包含两个Emoji
        if len(message_text) > 10:
            return
            
        emojis = self._extract_valid_emojis(message_text)
        if len(emojis) == 2:
            await self._process_mix_request(event, emojis)

    async def terminate(self):
        """清理资源（显式关闭HTTP连接）"""
        logger.info("EmojiMix插件已卸载")

