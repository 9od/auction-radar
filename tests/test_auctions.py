import json
import tempfile
import unittest
from pathlib import Path
from auction_model import (CONFIG, amount, date_only, empty_archive, in_scope, load_json,
                           merge_archive, normalize, region_of, state_of, write_json)
from scraper import parse_listing, parse_case_results, parse_result_table, CollectionError, BlockedError


def lot(**values):
    base = {'법원':'성남지원', '사건번호':'2025타경1234', '물건번호':'1',
            '소재지':'경기도 성남시 분당구 수내동 73 푸른마을 301동 105호',
            '용도':'아파트','전용면적':84.5,'감정가':2000000000,
            '최저입찰가':1500000000,'진행상황':'신건','매각기일':'2026.09.21'}
    base.update(values)
    return normalize(base)


class AuctionTests(unittest.TestCase):
    def test_budget_uses_minimum_includes_first_round_and_15b_boundary(self):
        self.assertTrue(in_scope(lot()))
        self.assertTrue(in_scope(lot(감정가=1500000000)))
        self.assertFalse(in_scope(lot(최저입찰가=1500000001)))
        self.assertFalse(in_scope(lot(최저입찰가=None)))
        self.assertFalse(in_scope(lot(최저입찰가=0)))

    def test_area_is_exclusive_not_supply_and_missing_rejected(self):
        for area in (84,84.99,135): self.assertTrue(in_scope(lot(전용면적=area)))
        for area in (83.99,135.01,165,None): self.assertFalse(in_scope(lot(전용면적=area)))
        self.assertFalse(in_scope(lot(용도='오피스텔')))

    def test_all_seoul_and_precise_regions(self):
        for district in ('강북구','마포구','은평구','중랑구','금천구'):
            self.assertEqual(region_of('서울특별시 '+district+' 테스트동'),'서울')
        for city in ('수원','안양','과천','하남'):
            self.assertEqual(region_of('경기도 '+city+'시 정자동'),city)
        self.assertIsNone(region_of('경기도 의정부시 금정동'))
        self.assertIsNone(region_of('부산광역시 중구 신장동'))
        self.assertEqual(region_of('경기도 성남시 수정구 위례광장로 1'),'위례')
        self.assertEqual(region_of('경기도 하남시 학암동 1'),'위례')

    def test_case_court_and_lot_identity_and_related_case_split(self):
        self.assertNotEqual(lot()['id'],lot(법원='서울중앙지방법원')['id'])
        self.assertNotEqual(lot()['id'],lot(물건번호='2')['id'])
        i=lot(사건번호='성남지원2025타경12342025타경5678(중복)')
        self.assertEqual(i['사건번호'],'2025타경1234')
        self.assertEqual(i['관련사건'],['2025타경5678'])

    def test_missing_listing_is_not_completed(self):
        a=merge_archive(empty_archive(),[lot()])
        b=merge_archive(a,[])
        self.assertEqual(len(b['items']),1)
        self.assertEqual(state_of(b['items'][0],today='2026-10-01'),'확인필요')
        self.assertEqual(state_of(lot(진행상황='재매각')),'확인필요')
        self.assertEqual(state_of(lot(진행상황='취하')),'종료')

    def test_history_retained_sale_rate_not_minimum_rate(self):
        a=merge_archive(empty_archive(),[lot()])
        sold=lot(진행상황='매각',낙찰가=1780000000)
        b=merge_archive(a,[sold])
        self.assertEqual(b['items'][0]['낙찰가율'],89)
        self.assertEqual(b['items'][0]['최저입찰가율'],75)
        self.assertEqual(len(b['items'][0]['이력']),2)
        self.assertEqual(len(merge_archive(b,[sold])['items'][0]['이력']),2)
        self.assertIsNone(lot(진행상황='매각')['낙찰가율'])

    def test_later_round_wins_but_old_result_stays_in_history(self):
        current=lot(매각기일='2026.10.21',진행상황='재매각',최저입찰가=1600000000)
        a=merge_archive(empty_archive(),[lot()])
        a=merge_archive(a,[current])
        a=merge_archive(a,[lot(진행상황='매각',낙찰가=1700000000)])
        self.assertEqual(a['items'][0]['매각일'],'2026-10-21')
        self.assertEqual(a['items'][0]['진행상황'],'재매각')
        self.assertEqual(len(a['items'][0]['이력']),3)

    def test_legacy_identity_migration_keeps_history(self):
        a=merge_archive(empty_archive(),[lot(물건번호=None)])
        b=merge_archive(a,[lot(진행상황='매각',낙찰가=1700000000)])
        self.assertEqual(len(b['items']),1)
        self.assertEqual(len(b['items'][0]['이력']),2)

    def test_money_and_dates(self):
        self.assertEqual(amount('1,500,000,000 (75%)'),1500000000)
        self.assertIsNone(amount('매각가격 미상'))
        self.assertEqual(date_only('경매1계2026.09.21'),'2026-09-21')
        self.assertIsNone(date_only('2026-02-31'))

    def test_corrupt_history_does_not_reset(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'archive.json'
            write_json(p,empty_archive())
            self.assertEqual(load_json(p)['schema_version'],2)
            p.write_text('{')
            with self.assertRaises(json.JSONDecodeError): load_json(p,empty_archive())

    def test_pair_parser_uses_building_area_and_preserves_lots(self):
        body='<table><tbody>'
        for seq in ('1','2'):
            body+=f'<tr><td></td><td>성남지원2025타경1234</td><td>{seq}</td><td>경기도 성남시 분당구 수내동 [토지 40㎡] [집합건물 철근콘크리트조 84.5㎡]</td><td></td><td></td><td>2,000,000,000원</td><td>2026.09.21</td></tr><tr><td>아파트</td><td>1,500,000,000원 (75%)</td><td>유찰 1회</td></tr>'
        rows=parse_listing(body+'</tbody></table>','성남지원')
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['전용면적'],84.5)
        self.assertEqual(rows[0]['최저입찰가'],1500000000)
        with self.assertRaises(CollectionError): parse_listing('<html>loading</html>')
        with self.assertRaises(BlockedError): parse_listing('<html>Web firewall security policy</html>')

    def test_case_result_price_not_guessed_and_lot_matched(self):
        payload={'data':{'dma_csBasInf':{'csNo':'2025타경1234'},'dlt_rletCsGdsDtsDxdyInf':[
            {'dspslGdsSeq':'1','dspslDxdyYmd':'20260921','rsltCd':'매각','lwsDspslPrc':'1500000000'},
            {'dspslGdsSeq':'2','dspslDxdyYmd':'20260921','rsltCd':'매각','dspslPrc':'1800000000'}]}}
        result=parse_case_results(payload,[lot()])
        self.assertEqual(len(result),1)
        self.assertIsNone(result[0]['낙찰가'])
        self.assertEqual(parse_case_results(payload,[lot(물건번호=None)]),[])
        payload['data']['ipcheck']=False
        with self.assertRaises(BlockedError):parse_case_results(payload,[lot()])

    def test_results_column_price_is_actual_sale(self):
        page='<table><thead><tr><th>사건번호</th><th>소재지</th><th>용도</th><th>면적</th><th>감정가</th><th>최저가격</th><th>매각가격</th><th>매각기일</th><th>결과</th></tr></thead><tbody><tr><td>2025타경1234</td><td>경기도 성남시 분당구 수내동</td><td>아파트</td><td>84㎡</td><td>2,000,000,000</td><td>1,500,000,000</td><td>1,780,000,000</td><td>2026.09.21</td><td>매각</td></tr></tbody></table>'
        i=parse_result_table(page,'성남지원')[0]
        self.assertEqual(i['낙찰가율'],89)
        self.assertEqual(i['최저입찰가율'],75)


class FailureAndPaginationTests(unittest.TestCase):
    def test_page_loader_retries_a_renderer_timeout(self):
        import sys
        from types import ModuleType
        from unittest.mock import patch
        from scraper import load_page

        class TimeoutException(Exception): pass
        class WebDriverException(Exception): pass
        exceptions = ModuleType('selenium.common.exceptions')
        exceptions.TimeoutException = TimeoutException
        exceptions.WebDriverException = WebDriverException
        support_ui = ModuleType('selenium.webdriver.support.ui')
        class Wait:
            def __init__(self, driver, seconds): self.driver = driver
            def until(self, predicate):
                if not predicate(self.driver): raise TimeoutException('not ready')
        support_ui.WebDriverWait = Wait
        modules = {'selenium': ModuleType('selenium'),
                   'selenium.common': ModuleType('selenium.common'),
                   'selenium.common.exceptions': exceptions,
                   'selenium.webdriver': ModuleType('selenium.webdriver'),
                   'selenium.webdriver.support': ModuleType('selenium.webdriver.support'),
                   'selenium.webdriver.support.ui': support_ui}
        class Driver:
            calls = 0
            page_source = '<html></html>'
            def get(self, url):
                self.calls += 1
                if self.calls == 1: raise TimeoutException('renderer timeout')
            def execute_script(self, script): pass
            def find_elements(self, by, value): return [object()] if self.calls > 1 else []
        driver = Driver()
        with patch.dict(sys.modules, modules), patch('scraper.time.sleep'):
            load_page(driver, 'https://example.test', ready_id='court')
        self.assertEqual(driver.calls, 2)

    def test_more_than_ten_pages_are_collected(self):
        from unittest.mock import patch
        from scraper import read_all_pages
        class Driver:
            page=1
            @property
            def page_source(self):return '<p>총 물건수 12건</p>'
            def find_elements(self,*args):return []
        driver=Driver()
        def parse(source,court):return [lot(물건번호=str(driver.page))]
        def advance(driver,wanted):driver.page=wanted;return True
        with patch('scraper.advance_page',advance):
            rows=read_all_pages(driver,parse,'성남지원',page_limit=0)
        self.assertEqual(len(rows),12)
        self.assertEqual(driver.page,12)

    def test_default_limit_stops_at_eight_without_requesting_ninth(self):
        from unittest.mock import patch
        from scraper import read_all_pages
        class Driver:
            page=1
            @property
            def page_source(self):return '<p>총 물건수 12건</p>'
            def find_elements(self,*args):return []
        driver=Driver()
        def parse(source,court):return [lot(물건번호=str(driver.page))]
        def advance(driver,wanted):
            self.assertLessEqual(wanted,8)
            driver.page=wanted
            return True
        with patch('scraper.advance_page',side_effect=advance) as move:
            rows=read_all_pages(driver,parse,'성남지원')
        self.assertEqual(len(rows),8)
        self.assertEqual(move.call_count,7)

    def test_collector_failure_keeps_last_data_and_reports_failure(self):
        import argparse
        from unittest.mock import patch
        from scraper import run
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/'auction_data.json'; archive=Path(td)/'archive.json'
            write_json(output,{'수집일시':'2026-09-01','items':[lot()]})
            args=argparse.Namespace(output=str(output),archive=str(archive),import_results=None,pages=0)
            with patch('scraper.make_driver',side_effect=RuntimeError('offline')),patch('builtins.print'):
                self.assertEqual(run(args),1)
            data=load_json(output)
            self.assertEqual(len(data['items']),1)
            self.assertEqual(data['수집일시'],'2026-09-01')
            self.assertFalse(data['수집상태']['전체성공'])
            self.assertEqual(len(load_json(archive)['items']),1)


if __name__=='__main__':unittest.main()
