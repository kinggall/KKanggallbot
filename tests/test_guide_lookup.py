import unittest

from guide_lookup import find_route, find_random_fleet, translate_route, guide_map, sortie_maps, missing_required_maps, map_fleet_sections, group_shared_fleets
from scripts.collect_zekamashi import extract_article, fleet_section_heading, obsolete_article, select_candidates


class GuideTranslationTests(unittest.TestCase):
    def test_any_map_options_are_not_missing_required_maps(self):
        req={'category':'sortie','sortie':[{'map':['4-1','4-2','4-3'],'any':True}]}
        self.assertEqual(missing_required_maps(req,{'4-2'}),set())
        req['sortie'][0]['any']=False
        self.assertEqual(missing_required_maps(req,{'4-2'}),{'4-1','4-3'})
        alternative={'category':'or','list':[req,{'category':'sortie','sortie':[{'map':'5-1'}]}]}
        self.assertEqual(missing_required_maps(alternative,{'5-1'}),set())
    def test_comment_pages_are_not_distinct_articles(self):
        choices={'https://zekamashi.net/kancolle-kouryaku/test/':'任務',
                 'https://zekamashi.net/kancolle-kouryaku/test/comment-page-2/':'任務 編成例'}
        selected=select_candidates(choices,{'wiki_id':'TEST','name_jp':'任務'})
        self.assertEqual(list(selected),['https://zekamashi.net/kancolle-kouryaku/test/'])

    def test_reviewed_year_and_variant_links(self):
        q={'wiki_id':'2610 F1','name_jp':'【期間限定】Halloweenの南瓜、食べりゅ?'}
        candidates={f'https://zekamashi.net/kancolle-kouryaku/{slug}/':q['name_jp']
                    for slug in ('2026pumpkin-7','2025pumpkin-w1')}
        self.assertEqual(list(select_candidates(candidates,q)),[
            'https://zekamashi.net/kancolle-kouryaku/2026pumpkin-7/'])

    def test_obsolete_guides_are_not_republished(self):
        self.assertTrue(obsolete_article('<h1>【一期】任務</h1><div class="entry-content"></div>'))
        self.assertTrue(obsolete_article('<h1>任務</h1><div class="entry-content"><p>※記事の編成例は一期の内容です。</p></div>'))
        self.assertFalse(obsolete_article('<h1>任務</h1><div class="entry-content"><p>一期画像は削除し二期編成に更新</p></div>'))

    def test_shared_map_notes_and_missing_colon(self):
        sections=map_fleet_sections('空母2重巡3駆逐1 ※任務条件\n4-1:【CFDGJ】(J:ボス)\n4-3【CFHN】(N:ボス)')
        self.assertEqual([r[0] for r in sections],['4-1','4-3'])
        self.assertNotIn('※',sections[0][1])
        sections=map_fleet_sections('軽空2駆逐4\n1-3:【CFJ】(J:ボス)\n1-4:ボス固定')
        self.assertIn('보스 도달 고정',sections[1][1])

    def test_photo_only_shared_fleet_does_not_invent_route(self):
        sections=map_fleet_sections('空母2軽巡1駆逐2水母1\n2-2:【CEK】(K:ボス)\n2-3:低確率(5%程度)で逸れあり')
        self.assertEqual([a for a,_ in sections],['2-2','2-3'])
        self.assertIn('경로 랜덤',sections[1][1])
    def test_old_article_prose_fleet_and_named_fleet(self):
        summary = find_random_fleet('今回は軽空2軽巡1水母1駆逐2の編成としています。※ボス固定不可能')
        self.assertIn('경항모2 경순1 수모1 구축2', summary)
        self.assertIn('경로 랜덤',summary)
        self.assertIsNone(find_random_fleet('自由枠に軽空母2採用'))
        self.assertIn('갬비어 베이',find_random_fleet('Gambier Bay Mk.II(旗艦)Fletcher空母2軽巡1駆逐1\n※ボス固定不可'))
        self.assertIn('갬비어 베이',translate_route(find_route('Gambier Bay Mk.II(旗艦)Fletcher空母2水母1軽巡1【BDHK】(K:ボス)')))

    def test_submarine_tender_shared_fleet_and_port_node(self):
        sections=map_fleet_sections('潜母(旗艦)1潜水2軽空母2水母1\n1-2:固定不可。ランダムで逸れます。\n2-1:【CEDH】(H:ボス)')
        self.assertEqual([s[0] for s in sections],['1-2','2-1'])
        self.assertEqual(guide_map('7-4O'),'7-4')

    def test_multiple_qualified_fleet_sections_no_reward_images(self):
        self.assertTrue(fleet_section_heading('編成例（羽黒神風駆逐４）'))
        self.assertFalse(fleet_section_heading('任務情報'))
        document=('<h1>試験任務</h1><div class="entry-content">'
                  '<h2>編成例（第一案）</h2><p><img src="/one.jpg"></p><p>駆逐6【AB】</p>'
                  '<h2>編成例（第二案）</h2><p><img src="/two.jpg"></p><p>軽巡1駆逐5【AC】</p>'
                  '<h2>まとめ</h2><img src="/reward.jpg"></div>')
        blocks,images=extract_article(document,'https://zekamashi.net/kancolle-kouryaku/test/','試験任務')
        self.assertEqual(images,['https://zekamashi.net/one.jpg','https://zekamashi.net/two.jpg'])
        self.assertEqual(len([b for b in blocks if '【' in b['text']]),2)

    def test_group_only_identical_fleets_and_images(self):
        entries = [('1-3', '경항모2 구축4\n【CFJ】', ['shared.jpg']),
                   ('1-4', '경항모2 구축4\n도중 2전 / 경로 랜덤', ['shared.jpg'])]
        self.assertEqual(group_shared_fleets(entries), [
            '1-3/1-4: 경항모2 구축4\n1-3: 【CFJ】\n1-4: 도중 2전 / 경로 랜덤'])
        self.assertEqual(len(group_shared_fleets([
            entries[0], ('1-4', entries[1][1], ['other.jpg'])])), 2)
        self.assertEqual(len(group_shared_fleets([
            entries[0], ('1-4', '경항모1 구축4\n경로 랜덤', ['shared.jpg'])])), 2)

    def test_shared_fleet_has_separate_map_routes(self):
        sections = map_fleet_sections('軽空2駆逐4\n1-3:【CFJ】(C:通常 F:通常 J:ボス)\n'
                                     '1-4:道中2戦固定(ランダム)\n※任務条件')
        self.assertEqual([area for area, _ in sections], ['1-3', '1-4'])
        self.assertEqual(sections[0][1], '경항모2 구축4 【CFJ】(C:통상 F:통상 J:보스)')
        self.assertEqual(sections[1][1], '경항모2 구축4\n도중 2전 / 경로 랜덤')
        self.assertNotIn('1-3:', sections[0][1])

    def test_gauge_maps_and_compact_queries(self):
        for value in ('722', '7-2-2', '７－２－２', '7-2M', '7-2-P2'):
            self.assertEqual(guide_map(value), '7-2-2')
        self.assertEqual(guide_map('732'), '7-3-2')
        self.assertEqual(guide_map('55'), '5-5')
        self.assertIsNone(guide_map('7222'))

    def test_only_unambiguous_gauge_is_inferred(self):
        maps = ['7-2-2', '7-3-2', '4-2']
        self.assertEqual(guide_map('7-2', maps), '7-2-2')
        self.assertEqual(guide_map('7-3', maps), '7-3-2')
        self.assertEqual(guide_map('7-2-1', maps), '7-2-1')
        self.assertEqual(guide_map('7-2', ['7-2-1', '7-2-2']), '7-2')

    def test_quest_map_arrays_preserve_gauges(self):
        self.assertEqual(sortie_maps({'requirements': [
            {'map': ['7-2M', '7-3P', '4-2']}, {'map': '7-2-2'}]}),
            ['7-2-2', '7-3-2', '4-2'])

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
