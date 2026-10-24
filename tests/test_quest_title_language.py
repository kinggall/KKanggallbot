import unittest
import quests
import guide_lookup

class QuestTitleLanguageTests(unittest.TestCase):
    def test_kure_is_not_truncated_in_title_search_or_guide(self):
        catalog=quests.catalog()
        row=catalog.items[catalog.by_code['b161']]
        self.assertIn('구레의 유키카제',row['name_ko'])
        self.assertIn('구레의 유키카제',catalog.reply('B161').splitlines()[0])
        self.assertIn(catalog.by_code['b161'],catalog.search_keys('구레'))
        self.assertIn('구레의 유키카제',catalog.reply('단양'))
        self.assertIn('구레의 유키카제',guide_lookup.build_preview('B161')[0].splitlines()[0])

    def test_reviewed_titles_are_translated(self):
        catalog=quests.catalog()
        expected={'B213':'하야나미 개2','F138':'함재형 개2','B133':'콩고 개2병',
                  'F128':'키리시마 개2병','C23':'개 유구모형','Cs5':'하계대연습','Cs6':'하계대연습'}
        for code,name in expected.items():
            row=catalog.items[catalog.by_code[code.casefold()]]
            self.assertIn(name,row['name_ko'])
            self.assertNotRegex(row['name_ko'],r'[\u3041-\u3096\u30a1-\u30fa\u4e00-\u9fff]')
            self.assertIn(name,catalog.detail(catalog.by_code[code.casefold()]).splitlines()[0])
        for code in ['B213','B133']:
            self.assertIn(expected[code],guide_lookup.build_preview(code)[0].splitlines()[0])

    def test_furniture_keeps_original_name(self):
        catalog=quests.catalog()
        self.assertIn('羽黒の護り',catalog.detail(catalog.by_code['b138']))
