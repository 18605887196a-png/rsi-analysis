#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""晨星持有人信息抓取模块

从晨星中国 (morningstar.cn) 抓取基金持有人持有信息：
  1. 基金经理自持
  2. 高管投研跟投
  3. 内部员工持有
  4. 基金公司直接持有
"""

import re
import time
import requests


def _clean_text(html_block):
    """去掉 HTML 标签，返回纯文本"""
    text = re.sub(r'<!--.*?-->', '', html_block)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_holding(text):
    """从文本中提取持有量（万份或未持有）"""
    # 优先匹配 >100万份 / >10万份 等
    m = re.search(r'>\s*(\d+)\s*万份', text)
    if m:
        return f'>{m.group(1)}万份'
    # 匹配 101.2万份 / 64.7万份 等
    m = re.search(r'(\d+\.?\d*)\s*万份', text)
    if m:
        return f'{m.group(1)}万份'
    # 匹配 988.34 份 等（少量）
    m = re.search(r'(\d+\.?\d*)\s*份', text)
    if m:
        return f'{m.group(1)}份'
    if '未持有' in text:
        return '未持有'
    return '—'


def _extract_est_amount(text):
    """提取估算金额"""
    m = re.search(r'估算金额\s*>\s*(\d+)\s*万元', text)
    if m:
        return f'>{m.group(1)}万元'
    m = re.search(r'估算金额\s*(\d+\.?\d*)\s*万元', text)
    if m:
        return f'{m.group(1)}万元'
    if '估算金额' in text and '—' in text[text.index('估算金额'):text.index('估算金额')+20]:
        return '—'
    return '—'


def _extract_change(text):
    """提取增减变动"""
    if '增持' in text:
        return '增持'
    if '减持' in text:
        return '减持'
    if '持平' in text:
        return '持平'
    return ''


def fetch_morningstar_holders(fund_code, timeout=20):
    """从晨星抓取基金持有人持有信息

    Args:
        fund_code: 基金代码，如 '000973'
        timeout: 请求超时秒数

    Returns:
        dict: {
            'fund_manager_holding': {holding, change, est_amount, report_date},
            'executive_holding':    {holding, change, est_amount, report_date},
            'employee_holding':     {holding, change_pct, total_pct, est_amount, report_date},
            'company_holding':      {holding, est_amount, report_date},
        }
        抓取失败返回 None
    """
    url = f'https://www.morningstar.cn/fund/{fund_code}.html'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/120.0.0.0 Safari/537.36',
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except Exception:
        return None

    html = resp.text
    result = {}

    # 内部人员持有区块日期
    m = re.search(r'内部人员持有.*?(\d{4}-\d{2}-\d{2})', html)
    internal_date = m.group(1) if m else ''

    # --- 1. 基金经理自持 ---
    block_start = html.find('基金经理自持')
    block_end = html.find('高管投研跟投', block_start) if block_start >= 0 else -1
    if block_start >= 0 and block_end >= 0:
        text = _clean_text(html[block_start:block_end])
        result['fund_manager_holding'] = {
            'holding': _extract_holding(text),
            'change': _extract_change(text),
            'est_amount': _extract_est_amount(text),
            'report_date': internal_date,
        }

    # --- 2. 高管投研跟投 ---
    block_start = html.find('高管投研跟投')
    block_end = html.find('内部员工持有', block_start) if block_start >= 0 else -1
    if block_start >= 0 and block_end >= 0:
        text = _clean_text(html[block_start:block_end])
        result['executive_holding'] = {
            'holding': _extract_holding(text),
            'change': _extract_change(text),
            'est_amount': _extract_est_amount(text),
            'report_date': internal_date,
        }

    # --- 3. 内部员工持有 ---
    block_start = html.find('内部员工持有')
    block_end = html.find('基金公司直接持有', block_start) if block_start >= 0 else -1
    if block_start >= 0 and block_end >= 0:
        text = _clean_text(html[block_start:block_end])
        emp_holding = _extract_holding(text)
        # 增减百分比：增持/减持 后面可能跟空格和负号
        m = re.search(r'增持\s*(\d+\.?\d*%)', text)
        emp_change_pct = m.group(1) if m else ''
        m = re.search(r'减持\s*(-?\d+\.?\d*%)', text)
        if m:
            val = m.group(1)
            emp_change_pct = val if val.startswith('-') else f'-{val}'
        # 占总份额比例
        m = re.search(r'占总份额比例\s*(\d+\.?\d*%)', text)
        emp_pct = m.group(1) if m else ''
        result['employee_holding'] = {
            'holding': emp_holding,
            'change_pct': emp_change_pct,
            'total_pct': emp_pct,
            'est_amount': _extract_est_amount(text),
            'report_date': internal_date,
        }

    # --- 4. 基金公司直接持有 ---
    block_start = html.find('基金公司直接持有')
    block_end = html.find('基金经理在管产品', block_start)
    if block_start >= 0:
        if block_end < 0:
            block_end = block_start + 3000
        text = _clean_text(html[block_start:block_end])
        # 公司持有的报告日期（可能和内部人员不同）
        m = re.search(r'(\d{4}-\d{2}-\d{2})', text)
        company_date = m.group(1) if m else internal_date
        result['company_holding'] = {
            'holding': _extract_holding(text),
            'est_amount': _extract_est_amount(text),
            'report_date': company_date,
        }

    # --- 5. 基金经理在管产品内部持有信息（兄弟基金表格）---
    block_start = html.find('基金经理在管产品内部持有信息')
    block_end = html.find('持有人结构', block_start) if block_start >= 0 else -1
    if block_start >= 0 and block_end >= 0:
        raw = html[block_start:block_end]
        # 用管道符替换HTML标签，保留结构
        text = re.sub(r'<!--.*?-->', '', raw)
        text = re.sub(r'<[^>]+>', '|', text)
        text = re.sub(r'&gt;', '>', text)
        text = re.sub(r'\|+', '|', text)
        text = re.sub(r'\s+', ' ', text).strip()

        # 提取基金经理名
        m = re.match(r'基金经理在管产品内部持有信息\s*\|\s*(\S+)\s*\|\s*基金经理', text)
        manager_name = m.group(1) if m else ''

        # 提取日期
        dates = re.findall(r'(\d{4}-\d{2}-\d{2})', text[:300])

        # 按管道符分割，解析基金行
        parts = [p.strip() for p in text.split('|')]
        funds_data = []
        i = 0
        while i < len(parts):
            if parts[i] in ('基金经理', '高管投研', '内部员工', '管理人', '本基金',
                            '基金经理在管产品内部持有信息', ''):
                i += 1
                continue
            if re.match(r'\d{4}-\d{2}-\d{2}', parts[i]):
                i += 1
                continue
            fund_name = parts[i]
            i += 1
            if i < len(parts) and parts[i] == '本基金':
                is_current = True
                i += 1
            else:
                is_current = False
            holdings = []
            while i < len(parts) and len(holdings) < 4:
                p = parts[i].strip()
                if p and (re.match(r'(>\d+\s*万份|\d+[\d,.]*\s*万份|\d+\.?\d*\s*份|10-50\s*万份|50-100\s*万份|0-10\s*万份|未持有)', p)):
                    holdings.append(p.replace(' ', ''))
                    i += 1
                else:
                    break
            if holdings:
                funds_data.append({
                    'name': fund_name,
                    'is_current': is_current,
                    'fund_manager': holdings[0] if len(holdings) > 0 else '',
                    'executive': holdings[1] if len(holdings) > 1 else '',
                    'employee': holdings[2] if len(holdings) > 2 else '',
                    'company': holdings[3] if len(holdings) > 3 else '',
                })
            else:
                i += 1

        # 把顶部卡片的增减/估算金额信息合并到本基金那行
        for f in funds_data:
            if f.get('is_current'):
                f['fm_change'] = result.get('fund_manager_holding', {}).get('change', '')
                f['fm_est_amount'] = result.get('fund_manager_holding', {}).get('est_amount', '—')
                f['exec_change'] = result.get('executive_holding', {}).get('change', '')
                f['exec_est_amount'] = result.get('executive_holding', {}).get('est_amount', '—')
                f['emp_change_pct'] = result.get('employee_holding', {}).get('change_pct', '')
                f['emp_total_pct'] = result.get('employee_holding', {}).get('total_pct', '')
                f['emp_est_amount'] = result.get('employee_holding', {}).get('est_amount', '—')

        # 只保留同名不同份额的兄弟基金
        def _strip_share_class(name):
            return re.sub(r'[A-Z]+$', '', name).strip()

        current_fund = next((f for f in funds_data if f.get('is_current')), None)
        sibling_funds = []
        if current_fund:
            base_name = _strip_share_class(current_fund['name'])
            sibling_funds = [f for f in funds_data if _strip_share_class(f['name']) == base_name]

        # 为非本基金的兄弟基金也抓取增减详细数据
        for sf in sibling_funds:
            if sf.get('is_current'):
                continue
            # 通过基金名称搜索代码，校验名称完全一致
            sf_code, sf_matched_name = _find_fund_code_by_name(sf['name'])
            if sf_code and sf_matched_name == sf['name']:
                sf['morningstar_code'] = sf_code
                sf_detail = _fetch_holding_details_only(sf_code)
                if sf_detail:
                    sf['fm_change'] = sf_detail.get('fm_change', '')
                    sf['fm_est_amount'] = sf_detail.get('fm_est_amount', '—')
                    sf['exec_change'] = sf_detail.get('exec_change', '')
                    sf['exec_est_amount'] = sf_detail.get('exec_est_amount', '—')
                    sf['emp_change_pct'] = sf_detail.get('emp_change_pct', '')
                    sf['emp_total_pct'] = sf_detail.get('emp_total_pct', '')
                    sf['emp_est_amount'] = sf_detail.get('emp_est_amount', '—')

        result['manager_funds'] = {
            'manager_name': manager_name,
            'report_dates': {
                'fund_manager': dates[0] if len(dates) > 0 else '',
                'executive': dates[1] if len(dates) > 1 else '',
                'employee': dates[2] if len(dates) > 2 else '',
                'company': dates[3] if len(dates) > 3 else '',
            },
            'funds': funds_data,
            'sibling_funds': sibling_funds,
        }

    # --- 6. 基金规模变动历史（来自天天基金）---
    scale = fetch_fund_scale_history(fund_code)
    if scale:
        result['scale_history'] = scale

    return result if result else None


def _find_fund_code_by_name(name, timeout=10):
    """通过基金名称搜索基金代码（天天基金搜索接口）
    返回 (code, matched_name) 或 (None, None)，matched_name 必须和 name 完全一致
    """
    import json as _json
    url = 'https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx'
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://fund.eastmoney.com/'}
    params = {'callback': 'jQuery', 'm': '1', 'key': name}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        m = re.search(r'jQuery\((.*)\)', resp.text)
        if m:
            data = _json.loads(m.group(1))
            if data.get('Datas'):
                for d in data['Datas']:
                    matched_name = d.get('NAME', '')
                    # 必须名称完全一致才返回
                    if matched_name == name:
                        return d.get('CODE'), matched_name
    except Exception:
        pass
    return None, None


def _fetch_holding_details_only(fund_code, timeout=15):
    """只抓取顶部卡片的增减详细数据（不复用完整 fetch 避免递归）"""
    url = f'https://www.morningstar.cn/fund/{fund_code}.html'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/120.0.0.0 Safari/537.36',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except Exception:
        return None

    html = resp.text
    result = {}

    # 基金经理自持
    bs = html.find('基金经理自持')
    be = html.find('高管投研跟投', bs) if bs >= 0 else -1
    if bs >= 0 and be >= 0:
        text = _clean_text(html[bs:be])
        result['fm_change'] = _extract_change(text)
        result['fm_est_amount'] = _extract_est_amount(text)

    # 高管投研跟投
    bs = html.find('高管投研跟投')
    be = html.find('内部员工持有', bs) if bs >= 0 else -1
    if bs >= 0 and be >= 0:
        text = _clean_text(html[bs:be])
        result['exec_change'] = _extract_change(text)
        result['exec_est_amount'] = _extract_est_amount(text)

    # 内部员工持有
    bs = html.find('内部员工持有')
    be = html.find('基金公司直接持有', bs) if bs >= 0 else -1
    if bs >= 0 and be >= 0:
        text = _clean_text(html[bs:be])
        m = re.search(r'增持\s*(\d+\.?\d*%)', text)
        result['emp_change_pct'] = m.group(1) if m else ''
        m = re.search(r'减持\s*(-?\d+\.?\d*%)', text)
        if m:
            val = m.group(1)
            result['emp_change_pct'] = val if val.startswith('-') else f'-{val}'
        m = re.search(r'占总份额比例\s*(\d+\.?\d*%)', text)
        result['emp_total_pct'] = m.group(1) if m else ''
        result['emp_est_amount'] = _extract_est_amount(text)

    return result if result else None


def fetch_fund_scale_history(fund_code, timeout=15):
    """从天天基金抓取基金季度规模变动历史

    Args:
        fund_code: 基金代码，如 '110018'
        timeout: 请求超时秒数

    Returns:
        list: [{date, purchase, redemption, total_shares, net_assets, change_pct}, ...]
        抓取失败返回 None
    """
    import json as _json
    url = 'https://fundf10.eastmoney.com/FundArchivesDatas.aspx'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/120.0.0.0 Safari/537.36',
        'Referer': f'https://fundf10.eastmoney.com/gmbd_{fund_code}.html',
    }
    params = {'type': 'gmbd', 'code': fund_code}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        resp.raise_for_status()
    except Exception:
        return None

    text = resp.text
    # 格式: var gmbd_apidata={ content:"<table>...</table>" }
    m = re.search(r'content:"(.*?)"', text, re.DOTALL)
    if not m:
        return None

    content = m.group(1)
    # 去掉HTML标签，用管道符分隔
    clean = re.sub(r'<[^>]+>', '|', content)
    clean = re.sub(r'&nbsp;', ' ', clean)
    clean = re.sub(r'\|+', '|', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()

    # 解析: |日期|期间申购（亿份）|期间赎回（亿份）|期末总份额（亿份）|期末净资产（亿元）|净资产变动率|2026-06-30|16.20|...
    parts = [p.strip() for p in clean.split('|') if p.strip()]

    # 跳过表头，找数据行
    scale_data = []
    i = 0
    # 跳过表头文字
    while i < len(parts):
        if re.match(r'\d{4}-\d{2}-\d{2}', parts[i]):
            break
        i += 1

    while i < len(parts):
        if not re.match(r'\d{4}-\d{2}-\d{2}', parts[i]):
            break
        date = parts[i]
        purchase = parts[i+1] if i+1 < len(parts) else ''
        redemption = parts[i+2] if i+2 < len(parts) else ''
        total_shares = parts[i+3] if i+3 < len(parts) else ''
        net_assets = parts[i+4] if i+4 < len(parts) else ''
        change_pct = parts[i+5] if i+5 < len(parts) else ''
        scale_data.append({
            'date': date,
            'purchase': purchase,         # 期间申购（亿份）
            'redemption': redemption,     # 期间赎回（亿份）
            'total_shares': total_shares, # 期末总份额（亿份）
            'net_assets': net_assets,     # 期末净资产（亿元）
            'change_pct': change_pct,     # 净资产变动率
        })
        i += 6

    return scale_data if scale_data else None
    """批量抓取持有人信息

    Args:
        fund_codes: 基金代码列表
        delay: 每次请求间隔秒数

    Returns:
        dict: {fund_code: holders_data}
    """
    results = {}
    for i, code in enumerate(fund_codes):
        print(f'  [{i+1}/{len(fund_codes)}] {code}...', end='', flush=True)
        data = fetch_morningstar_holders(code)
        if data:
            results[code] = data
            print(' ✓', flush=True)
        else:
            print(' 失败', flush=True)
        if i < len(fund_codes) - 1:
            time.sleep(delay)
    return results


if __name__ == '__main__':
    import json
    import sys

    code = sys.argv[1] if len(sys.argv) > 1 else '000973'
    data = fetch_morningstar_holders(code)
    if data:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f'获取 {code} 失败')