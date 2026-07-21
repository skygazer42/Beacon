import uuid
import secrets
import time
import re
def classify_data(data, pid, level=0):

    """分类数据。"""
    result = []

    for v in data:
        if v["pid"]==pid:
            v["level"] = level

            if "childs" not in v.keys():
                v["childs"]=[]

            inner_result = classify_data(data, v["id"], level + 1)

            if inner_result:
                for inner_v in inner_result:
                    v["childs"].append(inner_v)

            result.append(v)

    return result
def build_page_labels(page,page_num):
    """
    :param page: 当前页面
    :param page_num: 总页数
    :return:
    返回式例：
        [{'page': 1, 'name': 1, 'cur': True}, {'page': 2, 'name': 2, 'cur': False}, {'page': 2, 'name': '下一页'}]

    """

    page_labels = []
    if page_num <= 0:
        return page_labels

    page = max(1, min(int(page), int(page_num)))
    if page > 1:
        page_labels.append({
            "page": 1,
            "name": "首页"
        })
        page_labels.append({
            "page": page - 1,  # 当前页点击时候触发的页数
            "name": "上一页"
        })
    window_size = 5
    start_page = max(1, page - 2)
    end_page = min(page_num, start_page + window_size - 1)
    start_page = max(1, end_page - window_size + 1)
    page_array = list(range(start_page, end_page + 1))

    for p in page_array:
        if p <= page_num:
            if page==p:
                cur = 1
            else:
                cur = 0
            page_labels.append({
                "page": p,
                "name": p,
                "cur":cur
            })

    if end_page < page_num:
        page_labels.append({
            "page": page_num,
            "name": "尾页"
        })

    if page + 1 <= page_num:
        page_labels.append({
            "page": page + 1,
            "name": "下一页"
        })

    return page_labels


buildPageLabels = build_page_labels
def gen_random_code(prefix=""):
    """
    生产永远不重复的随机数
    :param prefix: 编码前缀
    :return:
    """
    d = time.strftime("%Y%m%d%H%M%S")
    prefix_text = "" if prefix is None else str(prefix)
    suffix = uuid.uuid4().hex[:8]
    code = "%s_%s_%s%d" % (prefix_text, d, suffix, 1000 + secrets.randbelow(9000))

    return code
def validate_email(s):
    """校验邮箱。"""
    ex_email = re.compile(r'(^[\w][a-zA-Z0-9.]{4,19})@[a-zA-Z0-9]{2,3}.com')
    r = ex_email.match(s)

    if r:
        return True
    else:
        return False
def validate_tel(s):
    """校验`tel`。"""
    ex_tel = re.compile(r'(^[0-9\-]{11,15})')
    r = ex_tel.match(s)

    if r:
        return True
    else:
        return False
