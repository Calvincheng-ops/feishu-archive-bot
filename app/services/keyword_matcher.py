"""关键词匹配引擎"""
import re
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class MatchResult:
    """匹配结果"""
    matched: bool
    keyword: Optional[str] = None
    confidence: float = 0.0


# 关键词模式列表
KEYWORD_PATTERNS = [
    # final 版本相关
    (r"(?:这是\s*)?final\s*(?:版本|版|稿)?", "final版本", 1.0),
    (r"(?:这是\s*)?最终(?:版本|版|稿)?", "最终版本", 1.0),
    (r"(?:这是\s*)?定稿", "定稿", 0.9),
    (r"(?:这是\s*)?正式(?:版本|版|稿)?", "正式版本", 0.9),
    
    # 归档指令
    (r"确认归档", "确认归档", 1.0),
    (r"请上传到云盘", "请上传到云盘", 1.0),
    (r"归档(?:此|这个|这个)文件", "归档文件", 0.9),
    (r"上传到(?:云盘|网盘|云空间)", "上传到云盘", 0.9),
    (r"保存到(?:云盘|网盘|云空间)", "保存到云盘", 0.8),
]


# 编译正则模式
COMPILED_PATTERNS = [
    (re.compile(pattern, re.IGNORECASE), keyword, confidence)
    for pattern, keyword, confidence in KEYWORD_PATTERNS
]


def match_keywords(text: str) -> MatchResult:
    """
    匹配消息文本中的关键词
    
    Args:
        text: 消息文本内容
        
    Returns:
        MatchResult: 匹配结果
    """
    if not text:
        return MatchResult(matched=False)
    
    for pattern, keyword, confidence in COMPILED_PATTERNS:
        if pattern.search(text):
            return MatchResult(
                matched=True,
                keyword=keyword,
                confidence=confidence
            )
    
    return MatchResult(matched=False)


def get_keyword_list() -> List[str]:
    """获取所有关键词列表（用于展示）"""
    return [keyword for _, keyword, _ in KEYWORD_PATTERNS]
