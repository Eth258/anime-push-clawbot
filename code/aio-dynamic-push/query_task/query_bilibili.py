import json
import re
import time

import requests
from collections import deque

from common import util
try:
    from dynamic_filter import classify
except Exception:  # 兼容包内导入
    from ..dynamic_filter import classify
try:
    from ai_filter import ai_classify
except Exception:
    from ..ai_filter import ai_classify
from common.cache import set_cached_value, get_cached_value
from common.logger import log
from common.proxy import my_proxy
from query_task import QueryTask


class QueryBilibili(QueryTask):
    def __init__(self, config):
        super().__init__(config)
        self.uid_list = config.get("uid_list", [])
        self.skip_forward = config.get("skip_forward", True)
        self.cookie = config.get("cookie", "")
        self.payload = config.get("payload", "")
        self.buvid3 = None

    def query(self):
        if not self.enable:
            return
        try:
            self.init_buvid3()
            current_time = time.strftime("%H:%M", time.localtime(time.time()))
            if self.begin_time <= current_time <= self.end_time:
                my_proxy.current_proxy_ip = my_proxy.get_proxy(proxy_check_url="http://api.bilibili.com/x/space/acc/info")
                if self.enable_dynamic_check:
                    for uid in self.uid_list:
                        self.query_dynamic_v2(uid)
                        time.sleep(1)
                if self.enable_living_check:
                    self.query_live_status_batch(self.uid_list)
                log.info(f"【B站-查询任务-{self.name}】本轮检查完成，UID {len(self.uid_list)} 个")
        except Exception as e:
            log.error(f"【B站-查询任务-{self.name}】出错：{e}", exc_info=True)

    def init_buvid3(self, get_from_cache=True):
        buvid3 = None
        if get_from_cache:
            buvid3 = get_cached_value("buvid3")
        if buvid3 is None:
            buvid3 = self.get_new_buvid3()
            set_cached_value("buvid3", buvid3)
        self.buvid3 = buvid3

    def get_new_buvid3(self):
        buvid3 = self.generate_buvid3()
        url = "https://api.bilibili.com/x/internal/gaia-gateway/ExClimbWuzhi"
        headers = {
            'content-type': 'application/json;charset=UTF-8',
            'cookie': f'buvid3={buvid3};'
        }
        payload = json.dumps({"payload": self.payload})
        response = util.requests_post(url, f"B站-查询动态状态-激活buvid3-{self.name}", headers=headers, data=payload, use_proxy=True)
        if util.check_response_is_ok(response):
            data = response.json()
            code = data.get("code", -1)
            message = data.get("message", "")
            if code == 0:
                log.info(f"【B站-查询动态状态-激活buvid3-{self.name}】激活成功")
            else:
                log.error(f"【B站-查询动态状态-激活buvid3-{self.name}】激活失败, code：{code}, message: {message}")
        else:
            log.error(f"【B站-查询动态状态-激活buvid3-{self.name}】激活失败")
        return buvid3

    def generate_buvid3(self):
        url = "https://api.bilibili.com/x/frontend/finger/spi"
        headers = {}
        response = util.requests_get(url, f"B站-查询动态状态-spi-{self.name}", headers=headers, use_proxy=True)
        if util.check_response_is_ok(response):
            try:
                result = json.loads(str(response.content, "utf-8"))
            except UnicodeDecodeError:
                log.error(f"【B站-查询动态状态-请求buvid3-{self.name}】解析content出错")
                return
            data = result.get("data")
            buvid3 = data.get("b_3")
            return buvid3
        return None

    def query_dynamic_v2(self, uid=None, is_retry_by_buvid3=False):
        if uid is None:
            return
        uid = str(uid)
        query_url = (f"https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
                     f"?host_mid={uid}&offset=&my_ts={int(time.time())}&features=itemOpusStyle")
        headers = self.get_headers(uid)
        if self.buvid3 is not None:
            headers['cookie'] = f"buvid3={self.buvid3};"
        if self.cookie != "":
            headers["cookie"] = self.cookie
        response = util.requests_get(query_url, f"B站-查询动态状态-{self.name}", headers=headers, use_proxy=True)
        if util.check_response_is_ok(response):
            try:
                result = json.loads(str(response.content, "utf-8"))
            except UnicodeDecodeError:
                log.error(f"【B站-查询动态状态-{self.name}】【{uid}】解析content出错")
                return
            if result["code"] != 0:
                log.error(f"【B站-查询动态状态-{self.name}】请求返回数据code错误：{result['code']}")
                if result["code"] == -352:
                    if is_retry_by_buvid3 is True:
                        log.error(f"【B站-查询动态状态-{self.name}】已经重试获取了【{uid}】，但依然失败")
                        return
                    self.init_buvid3(get_from_cache=False)
                    log.info(f"【B站-查询动态状态-{self.name}】重新获取到了buvid3：{self.buvid3}")
                    log.info(f"【B站-查询动态状态-{self.name}】重试获取【{uid}】的动态")
                    self.query_dynamic_v2(uid, is_retry_by_buvid3=True)
            else:
                data = result["data"]
                if "items" not in data or data["items"] is None or len(data["items"]) == 0:
                    log.warning(f"【B站-查询动态状态-{self.name}】【{uid}】接口返回空，跳过本轮（不建基线）")
                    return

                items = data["items"]
                # 循环遍历 items ，剔除不满足要求的数据
                items = [item for item in items if
                         (item["modules"].get("module_tag", None) is None or item["modules"].get("module_tag").get("text", None) != "置顶")  # 跳过置顶
                         ]

                # 跳过置顶后再判断一下，防止越界
                if len(data["items"]) == 0:
                    # 不创建带哨兵的队列：留空让下次成功请求时的「基线重建」生效
                    log.warning(f"【B站-查询动态状态-{self.name}】【{uid}】动态列表为空，跳过本轮（不建立基线）")
                    return

                item = items[0]
                # 取最新一条的信息（作者、头像）
                first = items[0]
                try:
                    uname = first["modules"]["module_author"]["name"]
                except KeyError:
                    log.error(f"【B站-查询动态状态-{self.name}】【{uid}】获取不到uname")
                    return

                avatar_url = None
                try:
                    avatar_url = first["modules"]["module_author"]["face"]
                except Exception:
                    log.error(f"【B站-查询动态状态-{self.name}】头像获取发生错误，uid：{uid}")

                if self.dynamic_dict.get(uid, None) is None:
                    self.dynamic_dict[uid] = deque(maxlen=self.len_of_deque)
                    for index in range(self.len_of_deque):
                        if index < len(items):
                            self.dynamic_dict[uid].appendleft(items[index]["id_str"])
                    log.info(f"【B站-查询动态状态-{self.name}】【{uname}】动态初始化：{self.dynamic_dict[uid]}")
                    return

                # 基线无效（首次运行，或上次接口返回空列表被塞了哨兵 -1）时，
                # 用当前列表重建基线，本轮不推送；否则会把整页历史动态当成新动态重推。
                dq = self.dynamic_dict.get(uid)
                if dq is None or not dq or (-1 in dq) or ("-1" in dq):
                    self.dynamic_dict[uid] = deque(maxlen=self.len_of_deque)
                    for it in items[:self.len_of_deque]:
                        self.dynamic_dict[uid].appendleft(it["id_str"])
                    log.info(f"【B站-查询动态状态-{self.name}】【{uname}】基线重建："
                             f"{len(self.dynamic_dict[uid])} 条（本轮不推送）")
                    return

                # 一次轮询可能有多条新动态，全部处理（最多 5 条，防止积压刷屏）
                seen = set(self.dynamic_dict[uid])
                new_items = [it for it in items if it["id_str"] not in seen][:5]
                if not new_items:
                    return
                log.info(f"【B站-查询动态状态-{self.name}】【{uname}】发现 {len(new_items)} 条新动态")

                for item in reversed(new_items):
                    dynamic_id = item["id_str"]
                    try:
                        self.dynamic_dict[uid].append(dynamic_id)
                        dynamic_type = item["type"]
                        allow_type_list = ["DYNAMIC_TYPE_DRAW",  # 带图/图文动态
                                           "DYNAMIC_TYPE_WORD",  # 纯文字动态
                                           "DYNAMIC_TYPE_AV",  # 投稿视频
                                           "DYNAMIC_TYPE_ARTICLE",  # 投稿专栏
                                           "DYNAMIC_TYPE_COMMON_SQUARE"  # 装扮
                                           ]
                        if self.skip_forward is False:
                            allow_type_list.append("DYNAMIC_TYPE_FORWARD")
                        if dynamic_type not in allow_type_list:
                            log.info(f"【B站-查询动态状态-{self.name}】【{uname}】动态类型不推送：{dynamic_type}")
                            continue

                        item_uname = item["modules"]["module_author"]["name"]
                        item_avatar = None
                        try:
                            item_avatar = item["modules"]["module_author"]["face"]
                        except Exception:
                            item_avatar = avatar_url

                        timestamp = int(item["modules"]["module_author"]["pub_ts"])
                        dynamic_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
                        module_dynamic = item["modules"]["module_dynamic"]

                        content = None
                        pic_url = None
                        title_msg = "发动态了"
                        if dynamic_type == "DYNAMIC_TYPE_FORWARD":
                            content = module_dynamic["desc"]["text"]
                            title_msg = "转发了动态"
                        elif dynamic_type == "DYNAMIC_TYPE_DRAW":
                            if module_dynamic["major"]["type"] == "MAJOR_TYPE_OPUS":
                                content = module_dynamic["major"]["opus"]["summary"]["text"]
                                try:
                                    title = module_dynamic["major"]["opus"]["title"]
                                    content = f"「{title}」{content}" if title else content
                                except Exception:
                                    pass
                                try:
                                    pic_url = module_dynamic["major"]["opus"]["pics"][0]["url"]
                                except Exception:
                                    pass
                            else:
                                content = module_dynamic["desc"]["text"]
                                pic_url = module_dynamic["major"]["draw"]["items"][0]["src"]
                        elif dynamic_type == "DYNAMIC_TYPE_WORD":
                            content = module_dynamic["desc"]["text"]
                        elif dynamic_type == "DYNAMIC_TYPE_AV":
                            content = module_dynamic["major"]["archive"]["title"]
                            pic_url = module_dynamic["major"]["archive"]["cover"]
                            title_msg = "投稿了"
                        elif dynamic_type == "DYNAMIC_TYPE_ARTICLE":
                            content = module_dynamic["major"]["opus"]["title"]
                            try:
                                pic_url = module_dynamic["major"]["opus"]["pics"][0]["url"]
                            except Exception:
                                pass
                        elif dynamic_type == "DYNAMIC_TYPE_COMMON_SQUARE":
                            content = module_dynamic["desc"]["text"]

                        # 只推番剧内容：先让 AI 判断，失败再回退关键词规则
                        keep, why = None, ""
                        try:
                            verdict = ai_classify(content or "", dynamic_type,
                                                  title_msg, item_uname)
                            if verdict is not None:
                                keep, reason, category = verdict
                                why = "AI:%s/%s" % (category, reason)
                        except Exception:
                            pass
                        if keep is None:
                            keep, why = classify(content or "", dynamic_type, title_msg)
                            why = "规则:" + why

                        if not keep:
                            log.info(f"【B站-查询动态状态-{self.name}】【{item_uname}】跳过非番剧动态：{why} | {(content or '')[:30]}")
                            continue

                        log.info(f"【B站-查询动态状态-{self.name}】【{item_uname}】准备推送({why})：{(content or '')[:30]}")
                        self.push_for_bili_dynamic(item_uname, dynamic_id, content, pic_url, dynamic_type,
                                                   dynamic_time, title_msg, dynamic_raw_data=item,
                                                   avatar_url=item_avatar)
                    except Exception as e:
                        log.error(f"【B站-查询动态状态-{self.name}】推送单条动态出错：{e}")

    @DeprecationWarning
    def query_dynamic(self, uid=None):
        if uid is None:
            return
        uid = str(uid)
        query_url = (f"http://api.vc.bilibili.com/dynamic_svr/v1/dynamic_svr/space_history"
                     f"?host_uid={uid}&offset_dynamic_id=0&need_top=0&platform=web&my_ts={int(time.time())}")
        headers = self.get_headers(uid)
        if self.cookie != "":
            headers["cookie"] = self.cookie
        response = util.requests_get(query_url, f"B站-查询动态状态-{self.name}", headers=headers, use_proxy=True)
        if util.check_response_is_ok(response):
            try:
                result = json.loads(str(response.content, "utf-8"))
            except UnicodeDecodeError:
                log.error(f"【B站-查询动态状态-{self.name}】【{uid}】解析content出错")
                return
            if result["code"] != 0:
                log.error(f"【B站-查询动态状态-{self.name}】请求返回数据code错误：{result['code']}")
            else:
                data = result["data"]
                if 'cards' not in data or data["cards"] is None or len(data["cards"]) == 0:
                    log.warning(f"【B站-查询动态状态-{self.name}】【{uid}】接口返回空，跳过本轮（不建基线）")
                    return

                item = data["cards"][0]
                dynamic_id = item["desc"]["dynamic_id"]
                try:
                    uname = item["desc"]["user_profile"]["info"]["uname"]
                except KeyError:
                    log.error(f"【B站-查询动态状态-{self.name}】【{uid}】获取不到uname")
                    return

                if self.dynamic_dict.get(uid, None) is None:
                    self.dynamic_dict[uid] = deque(maxlen=self.len_of_deque)
                    cards = data["cards"]
                    for index in range(self.len_of_deque):
                        if index < len(cards):
                            self.dynamic_dict[uid].appendleft(cards[index]["desc"]["dynamic_id"])
                    log.info(f"【B站-查询动态状态-{self.name}】【{uname}】动态初始化：{self.dynamic_dict[uid]}")
                    return

                if dynamic_id not in self.dynamic_dict[uid]:
                    previous_dynamic_id = self.dynamic_dict[uid].pop()
                    self.dynamic_dict[uid].append(previous_dynamic_id)
                    log.info(f"【B站-查询动态状态-{self.name}】【{uname}】上一条动态id[{previous_dynamic_id}]，本条动态id[{dynamic_id}]")
                    self.dynamic_dict[uid].append(dynamic_id)
                    log.debug(self.dynamic_dict[uid])

                    dynamic_type = item["desc"]["type"]
                    if dynamic_type not in [2, 4, 8, 64]:
                        log.info(f"【B站-查询动态状态-{self.name}】【{uname}】动态有更新，但不在需要推送的动态类型列表中")
                        return

                    timestamp = int(item["desc"]["timestamp"])
                    dynamic_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
                    card_str = item["card"]
                    card = json.loads(card_str)

                    content = None
                    pic_url = None
                    title_msg = "发动态了"
                    if dynamic_type == 1:
                        # 转发动态
                        content = card["item"]["content"]
                        title_msg = "转发了动态"
                    elif dynamic_type == 2:
                        # 图文动态
                        content = card["item"]["description"]
                        pic_url = card["item"]["pictures"][0]["img_src"]
                    elif dynamic_type == 4:
                        # 文字动态
                        content = card["item"]["content"]
                    elif dynamic_type == 8:
                        # 投稿动态
                        content = card["title"]
                        pic_url = card["pic"]
                        title_msg = "投稿了"
                    elif dynamic_type == 64:
                        # 专栏动态
                        content = card["title"]
                        pic_url = card["image_urls"][0]
                    log.info(f"【B站-查询动态状态-{self.name}】【{uname}】动态有更新，准备推送：{content[:30]}")
                    self.push_for_bili_dynamic(uname, dynamic_id, content, pic_url, dynamic_type, dynamic_time, title_msg, dynamic_raw_data=item)

    def query_live_status_batch(self, uid_list=None):
        if uid_list is None:
            uid_list = []
        if len(uid_list) == 0:
            return
        query_url = "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids"
        headers = self.get_headers(uid_list[0])
        if self.cookie != "":
            headers["cookie"] = self.cookie
        data = json.dumps({
            "uids": list(map(int, uid_list))
        })
        response = util.requests_post(query_url, "B站-查询直播状态", headers=headers, data=data, use_proxy=True)
        if util.check_response_is_ok(response):
            result = json.loads(str(response.content, "utf-8"))
            if result["code"] != 0:
                log.error(f"【B站-查询直播状态-{self.name}】请求返回数据code错误：{result['code']}")
            else:
                live_status_list = result["data"]
                if len(live_status_list) == 0:
                    return
                for uid, item_info in live_status_list.items():
                    try:
                        uname = item_info["uname"]
                        live_status = item_info["live_status"]
                    except (KeyError, TypeError):
                        log.error(f"【B站-查询直播状态-{self.name}】【{uid}】获取不到live_status")
                        continue

                    avatar_url = None
                    try:
                        avatar_url = item_info["face"]
                    except Exception:
                        log.error(f"【B站-查询动态状态-{self.name}】头像获取发生错误，uid：{uid}")

                    if self.living_status_dict.get(uid, None) is None:
                        self.living_status_dict[uid] = live_status
                        log.info(f"【B站-查询直播状态-{self.name}】【{uname}】初始化")
                        continue

                    if self.living_status_dict.get(uid, None) != live_status:
                        self.living_status_dict[uid] = live_status

                        room_id = item_info["room_id"]
                        room_title = item_info["title"]
                        room_cover_url = item_info["cover_from_user"]

                        if live_status == 1:
                            log.info(f"【B站-查询直播状态-{self.name}】【{uname}】开播了，准备推送：{room_title}")
                            self.push_for_bili_live(uname, room_id, room_title, room_cover_url, avatar_url=avatar_url)

    @staticmethod
    def get_headers(uid):
        return {
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "no-cache",
            "cookie": "l=v;",
            "origin": "https://space.bilibili.com",
            "pragma": "no-cache",
            "referer": f"https://space.bilibili.com/{uid}/dynamic",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
        }


    def _video_url(self, raw, content):
        """动态若是投稿视频, 返回带分P的视频链接; 否则返回动态页链接"""
        did = (raw or {}).get("id_str") or ""
        opus = f"https://www.bilibili.com/opus/{did}" if did else ""
        try:
            arc = (((raw or {}).get("modules") or {}).get("module_dynamic") or {}) \
                .get("major", {}).get("archive") or {}
        except Exception:
            arc = {}
        bvid = arc.get("bvid") or ""
        if not bvid:
            jump = arc.get("jump_url") or ""
            m = re.search(r"(BV[0-9A-Za-z]{10})", jump)
            bvid = m.group(1) if m else ""
        if not bvid:
            return opus

        base = f"https://www.bilibili.com/video/{bvid}"
        try:
            headers = {"User-Agent": "Mozilla/5.0", "Referer": base}
            if self.cookie:
                headers["Cookie"] = self.cookie
            r = requests.get("https://api.bilibili.com/x/web-interface/view",
                             params={"bvid": bvid}, headers=headers, timeout=15)
            data = r.json()
            pages = ((data.get("data") or {}).get("pages") or [])
            if len(pages) <= 1:
                return base
            # 从正文里找集数：第N集 > 全N集 > [N]
            text = content or ""
            m = re.search(r"第\s*(\d{1,3})\s*[集话話]", text)
            if not m:
                m = re.search(r"全\s*(\d{1,3})\s*[集话話]", text)
            if not m:
                m = re.search(r"\[(\d{1,3})\]", text)
            ep = int(m.group(1)) if m else None
            if ep is not None:
                ep = min(ep, len(pages))
            for pg in pages:
                title = pg.get("part") or ""
                if ep is not None and re.search(r"(?:第\s*%d\s*[集话話]|\bP?%d\b)" % (ep, ep), title):
                    return f"{base}?p={pg.get('page')}"
            # 找不到就按集数直接当分P序号（1 起）
            if ep is not None and 1 <= ep <= len(pages):
                return f"{base}?p={ep}"
            return f"{base}?p=1"
        except Exception:
            return base

    def push_for_bili_dynamic(self, uname=None, dynamic_id=None, content=None, pic_url=None,
                              dynamic_type=None, dynamic_time=None, title_msg='发动态了', dynamic_raw_data=None, avatar_url=None):
        """
        B站动态提醒推送
        :param uname: up主名字
        :param dynamic_id: 动态id
        :param content: 动态内容
        :param pic_url: 动态图片
        :param dynamic_type: 动态类型
        :param dynamic_time: 动态发送时间
        :param title_msg: 推送标题
        :param dynamic_raw_data: 动态原始数据
        :param avatar_url: 头像url
        """
        if uname is None or dynamic_id is None or content is None:
            log.error(f"【B站-动态提醒推送-{self.name}】缺少参数，uname:[{uname}]，dynamic_id:[{dynamic_id}]，content:[{content[:30]}]")
            return

        title = f"【B站】【{uname}】{title_msg}"
        content = f"{content[:100] + (content[100:] and '...')}[{dynamic_time}]"
        dynamic_url = self._video_url(dynamic_raw_data, content)
        extend_data = {
            'dynamic_raw_data': dynamic_raw_data,
            'avatar_url': avatar_url,
            'up_name': uname,
        }
        super().push(title, content, dynamic_url, pic_url, extend_data=extend_data)

    def push_for_bili_live(self, uname=None, room_id=None, room_title=None, room_cover_url=None, avatar_url=None):
        """
        B站直播提醒推送
        :param uname: up主名字
        :param room_id: 直播间id
        :param room_title: 直播间标题
        :param room_cover_url: 直播间封面
        :param avatar_url: 头像url
        """
        title = f"【B站】【{uname}】开播了"
        live_url = f"https://live.bilibili.com/{room_id}"
        extend_data = {
            'avatar_url': avatar_url,
        }
        super().push(title, room_title, live_url, room_cover_url, extend_data=extend_data)
