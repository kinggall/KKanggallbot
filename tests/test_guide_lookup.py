import unittest

from guide_lookup import find_route, translate_route


class GuideTranslationTests(unittest.TestCase):
    def test_speed_class_and_numeric_constraints(self):
        self.assertEqual(translate_route('重巡級1潜母1揚陸艦1(高速+統一)'),
                         '중순급1 잠수항모1 상륙함1(고속+통일)')
        self.assertIn('드럼통', translate_route('ドラム缶を2隻に装備'))
        self.assertIn('2척에 장착', translate_route('ドラム缶を2隻に装備'))
        self.assertIn('4이상', translate_route('駆逐4以上の編成で【ACL】').replace(' ', ''))

    def test_named_fleet_after_a_separate_comment(self):
        route = find_route('駆逐1を軽巡1に変更可能です。 羽黒足柄神風軽巡1駆逐2【ACDGP】(C:通常 P:ボス)')
        self.assertTrue(route.startswith('羽黒足柄神風'))
        self.assertIn('하구로 아시가라 카미카제 경순1 구축2', translate_route(route))

    def test_nested_route_and_related_quest_reference(self):
        route = find_route('航巡4駆逐2\n【DGIOPKEQ】(I:夜戦 (P:夜戦) K:夜戦 Q:ボス) ※注記')
        self.assertIn('Q:보스)', translate_route(route))
        self.assertNotIn('※', route)
        self.assertIsNone(find_route('軽空母で【空母戦力の投入による兵站線戦闘哨戒】'))
