import csv
import json
import tempfile
import unittest
from pathlib import Path
from src.sources.chotot.parsing import money, price, mileage
from src.sources.chotot.unified import normalize, export
from src.sources.chotot.robots import Robots, canonical

class PipelineTests(unittest.TestCase):
    def test_vietnamese_prices(self):
        for raw, expected in [('550 triệu',550000000),('1 tỷ 250 tr',1250000000),
            ('1,25 tỷ',1250000000),('1.25 tỷ',1250000000),('465.000.000 đ',465000000),
            ('465,000,000 VND',465000000),('465000000',465000000)]:
            with self.subTest(raw=raw): self.assertEqual(money(raw),expected)
        for raw in ['',None,'0','-500 triệu','2020 liên hệ 0901234567','500-600 triệu']:
            with self.subTest(raw=raw): self.assertIsNone(money(raw))

    def test_down_payment_vs_financing_offer(self):
        self.assertEqual(price('45.000.000 đ','Chỉ trảtrước 45tr NHẬNXE')[1],'instalment')
        self.assertEqual(price('465.000.000 đ','Honda City', ['Hỗ trợ trả góp'])[0],465000000)
        self.assertEqual(price('465.000.000 đ','Honda City', ['Trả trước 100 triệu'])[1],'full')
        self.assertEqual(price('45.000.000 đ','Xe đẹp', ['Trả trước 45 triệu'])[1],'instalment')
        self.assertEqual(price('45.000.000 đ','Xe đẹp', ['Trả trước 45.000.000 VNĐ'])[1],'instalment')
        self.assertEqual(price('500 triệu','Xe chỉ trả trước 100tr')[1],'invalid')
        self.assertEqual(price('Thỏa thuận')[1],'negotiable')
        self.assertIsNone(price('5 triệu/tháng')[0])

    def test_mileage_and_missing(self):
        self.assertEqual(mileage('25.000'),25000)
        self.assertEqual(mileage('6,5 vạn'),65000)
        self.assertEqual(mileage('0'),0)
        self.assertIsNone(mileage(None))
        self.assertIsNone(mileage('Đã sử dụng'))

    def test_robots_wildcards(self):
        r=Robots('User-agent: *\nAllow: /\nDisallow: /*page=\nDisallow: /private/\nAllow: /private/public$\nCrawl-delay: 3\nUser-agent: GPTBot\nDisallow: /')
        self.assertTrue(r.allowed('https://xe.chotot.com/mua-ban-oto-can-tho'))
        self.assertFalse(r.allowed('https://xe.chotot.com/mua-ban-oto?page=2'))
        self.assertFalse(r.allowed('https://xe.chotot.com/private/x'))
        self.assertTrue(r.allowed('https://xe.chotot.com/private/public'))
        self.assertFalse(r.allowed('https://xe.chotot.com/private/public/other'))
        self.assertEqual(r.delay,3)
        self.assertFalse(Robots('User-agent: *\nAllow: /\nUser-agent: MyBot\nDisallow: /', 'MyBot').allowed('https://xe.chotot.com/'))

    def test_url_scope(self):
        self.assertIsNone(canonical('https://evil.example/mua-ban-oto/123.htm'))
        self.assertIsNone(canonical('https://xe.chotot.com/cua-hang/x'))
        self.assertEqual(canonical('/mua-ban-oto-can-tho#x'),'https://xe.chotot.com/mua-ban-oto-can-tho')

    def test_real_pilot_and_schema(self):
        raws=[json.loads(x) for x in (Path(__file__).with_name('fixtures')/'raw.jsonl').read_text(encoding='utf-8').splitlines()]
        honda,flags,reasons=normalize(raws[0])
        self.assertEqual(honda['price_vnd'],465000000)
        self.assertEqual(honda['mileage_km'],25000)
        self.assertEqual(honda['sub_model_trim'],'RS')
        self.assertIsNone(honda['engine_capacity']); self.assertIsNone(honda['listing_date'])
        vf5,flags,reasons=normalize(raws[3])
        self.assertIsNone(vf5['price_vnd'])
        self.assertEqual(vf5['price_status'],'instalment')
        self.assertIn('new_vehicle_claim',reasons)
        self.assertEqual(normalize(raws[1])[0]['seller_type'], 'Unknown')
        self.assertEqual(normalize(raws[1])[0]['location_province'],'Bình Dương')
        with tempfile.TemporaryDirectory() as d:
            report=export(raws+[raws[0]],Path(d))
            self.assertEqual(report['unique_records'],6)
            self.assertEqual(report['duplicate_captures'],1)
            self.assertEqual(report['clean_records'],5)
            self.assertEqual(report['review_records'],1)
            for file,n in [('clean_21.csv',21),('chotot_mien_nam.csv',21)]:
                target = Path(d)/file if file == 'chotot_mien_nam.csv' else Path(d)/'chotot_mien_nam'/file
                with target.open(encoding='utf-8-sig',newline='') as f:
                    rows=list(csv.reader(f)); self.assertTrue(all(len(r)==n for r in rows))
                    self.assertEqual(len(rows),6)

if __name__=='__main__': unittest.main()
