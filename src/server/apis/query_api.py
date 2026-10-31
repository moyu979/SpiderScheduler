"""
查询 API：为前端提供作品/用户的组合筛选查询与统计

筛选维度可任意组合：
- website：逗号分隔多选
- state：逗号分隔多选；特殊值 none 表示 state 为 NULL（旧数据）
- 作者（works）：authorId，经 upload 关联（EXISTS，不改变行数）
- 日期：works 可选 upTime/downloadDate，users 固定 addTime；值按字符串比较，
  对 ISO 格式（downloadDate/addTime 及部分站点的 upTime）可靠
- keyword：works 匹配 title/workNumber，positions 匹配 authorId
- 分页：limit（默认 50，上限 500）/ offset；排序字段走白名单
"""

from flask import Blueprint, request, jsonify
from sqlalchemy import exists, func, or_, tuple_

from src.utils.logging.logger import SpiderLogger as logger
from src.utils.database.database import DatabaseManager
from src.utils.database.models import Works, PublishPos, Upload

WORK_DATE_FIELDS = {'upTime': Works.upTime, 'downloadDate': Works.downloadDate}
WORK_SORT_FIELDS = {
    'downloadPriority': Works.downloadPriority,
    'upTime': Works.upTime,
    'downloadDate': Works.downloadDate,
    'workNumber': Works.workNumber,
    'state': Works.state,
}
POS_DATE_FIELDS = {'addTime': PublishPos.addTime}
POS_SORT_FIELDS = {'addTime': PublishPos.addTime, 'authorId': PublishPos.authorId}

MAX_LIMIT = 500


def _csv(name):
    """逗号分隔的查询参数 → 去空列表"""
    raw = request.args.get(name, '') or ''
    return [v.strip() for v in raw.split(',') if v.strip()]


def _int_arg(name, default, minimum, maximum):
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _state_conditions(column, states):
    """state 多选；'none' 表示 NULL（兼容更新器启用前的旧数据）"""
    conds = []
    for s in states:
        if s.lower() == 'none':
            conds.append(column.is_(None))
        else:
            conds.append(column == s)
    return or_(*conds)


def _date_conditions(column, date_from, date_to):
    """日期区间：字符串比较，to 端补时间上限以覆盖整天"""
    conds = []
    if date_from:
        conds.append(column >= date_from)
    if date_to:
        conds.append(column <= f"{date_to}T99:99:99")
    return conds


def _apply_common_filters(query, model, date_fields, sort_fields, default_sort):
    """website / state / 日期 / keyword / 排序 的公共拼装"""
    websites = _csv('website')
    if websites:
        query = query.filter(model.website.in_(websites))

    states = _csv('state')
    if states:
        query = query.filter(_state_conditions(model.state, states))

    date_field = (request.args.get('date_field') or '').strip()
    date_from = (request.args.get('date_from') or '').strip()
    date_to = (request.args.get('date_to') or '').strip()
    if not date_field and (date_from or date_to):
        # 未指定日期字段但给了区间时，取该模型的默认日期字段（字典第一个）
        date_field = next(iter(date_fields))
    if date_field:
        column = date_fields.get(date_field)
        if column is None:
            raise ValueError(f"不支持的日期字段: {date_field}（可选: {', '.join(date_fields)}）")
        query = query.filter(*_date_conditions(column, date_from, date_to))

    keyword = (request.args.get('keyword') or '').strip()
    if keyword:
        if model is Works:
            query = query.filter(or_(
                Works.title.contains(keyword, autoescape=True),
                Works.workNumber.contains(keyword, autoescape=True),
            ))
        else:
            query = query.filter(PublishPos.authorId.contains(keyword, autoescape=True))

    sort_key = (request.args.get('sort') or default_sort).strip()
    sort_column = sort_fields.get(sort_key)
    if sort_column is None:
        raise ValueError(f"不支持的排序字段: {sort_key}（可选: {', '.join(sort_fields)}）")
    order = (request.args.get('order') or 'desc').lower()
    query = query.order_by(sort_column.desc() if order == 'desc' else sort_column.asc())
    # 稳定排序兜底，保证分页不重不漏
    if model is Works:
        query = query.order_by(Works.workNumber.asc(), Works.website.asc())
    else:
        query = query.order_by(PublishPos.authorId.asc(), PublishPos.website.asc())
    return query


def _page_args():
    return _int_arg('limit', 50, 1, MAX_LIMIT), max(_int_arg('offset', 0, 0, 10 ** 9), 0)


def _err(message, code=400):
    return jsonify({'success': False, 'error': message}), code


class QueryApi:
    """查询统计 API 类"""

    def __init__(self):
        self.blueprint = Blueprint('query_api', __name__, url_prefix='/api/query')
        self._register_routes()

    def _register_routes(self):

        @self.blueprint.route('/works')
        def query_works():
            """组合筛选作品列表"""
            try:
                limit, offset = _page_args()
                with DatabaseManager.get_db_session() as session:
                    query = session.query(Works)

                    # 作者筛选：存在任一 (website, workNumber, authorId) 关联即可
                    author = (request.args.get('author') or '').strip()
                    if author:
                        query = query.filter(exists().where(
                            Upload.authorId == author,
                            Upload.website == Works.website,
                            Upload.workNumber == Works.workNumber,
                        ))

                    query = _apply_common_filters(query, Works, WORK_DATE_FIELDS, WORK_SORT_FIELDS,
                                                  default_sort='downloadPriority')

                    total = query.count()
                    rows = query.offset(offset).limit(limit).all()

                    items = []
                    for w in rows:
                        item = {
                            'workNumber': w.workNumber,
                            'website': w.website,
                            'upTime': w.upTime,
                            'title': w.title,
                            'kind': w.kind,
                            'state': w.state,
                            'downloadDate': w.downloadDate,
                            'downloadPriority': w.downloadPriority,
                            'downloadInfo': _safe_json(w.downloadInfo),
                            'otherInfo': _safe_json(w.otherInfo),
                        }
                        if isinstance(item['otherInfo'], dict):
                            item['siteState'] = item['otherInfo'].get('siteState')
                        items.append(item)

                return jsonify({'success': True, 'total': total, 'limit': limit,
                                'offset': offset, 'items': items})
            except ValueError as e:
                return _err(str(e))
            except Exception as e:
                logger.error(f"查询作品失败: {e}")
                return _err(f"查询作品失败: {str(e)}", 500)

        @self.blueprint.route('/positions')
        def query_positions():
            """组合筛选发布位点列表（附带每个位点的作品关联数）"""
            try:
                limit, offset = _page_args()
                with DatabaseManager.get_db_session() as session:
                    query = session.query(PublishPos)
                    query = _apply_common_filters(query, PublishPos, POS_DATE_FIELDS, POS_SORT_FIELDS,
                                                  default_sort='addTime')

                    total = query.count()
                    rows = query.offset(offset).limit(limit).all()

                    # 批量取本页位点的 upload 计数，避免逐行查询
                    keys = [(pos.website, pos.authorId) for pos in rows]
                    counts = {}
                    if keys:
                        count_rows = (
                            session.query(Upload.website, Upload.authorId, func.count(Upload.workNumber))
                            .where(tuple_(Upload.website, Upload.authorId).in_(keys))
                            .group_by(Upload.website, Upload.authorId)
                            .all()
                        )
                        counts = {(w, uid): c for w, uid, c in count_rows}

                    items = [{
                        'authorId': pos.authorId,
                        'website': pos.website,
                        'state': pos.state,
                        'addTime': pos.addTime,
                        'workCount': counts.get((pos.website, pos.authorId), 0),
                    } for pos in rows]

                return jsonify({'success': True, 'total': total, 'limit': limit,
                                'offset': offset, 'items': items})
            except ValueError as e:
                return _err(str(e))
            except Exception as e:
                logger.error(f"查询位点失败: {e}")
                return _err(f"查询位点失败: {str(e)}", 500)

        @self.blueprint.route('/stats')
        def query_stats():
            """按 website × state 的计数统计，供前端生成筛选选项和概览条"""
            try:
                with DatabaseManager.get_db_session() as session:
                    work_rows = (
                        session.query(Works.website, Works.state, func.count(Works.workNumber))
                        .group_by(Works.website, Works.state)
                        .all()
                    )
                    pos_rows = (
                        session.query(PublishPos.website, PublishPos.state, func.count(PublishPos.authorId))
                        .group_by(PublishPos.website, PublishPos.state)
                        .all()
                    )

                def build(rows):
                    result = {}
                    for website, state, count in rows:
                        site = result.setdefault(website, {})
                        site[state if state is not None else 'none'] = count
                    return result

                return jsonify({
                    'success': True,
                    'works': build(work_rows),
                    'positions': build(pos_rows),
                })
            except Exception as e:
                logger.error(f"查询统计失败: {e}")
                return _err(f"查询统计失败: {str(e)}", 500)


def _safe_json(raw):
    """downloadInfo/otherInfo 是 JSON 文本；能解析则给对象，否则原样返回"""
    if raw is None:
        return None
    try:
        import json
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw
