from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def main():
    runner = CliRunner()
    with patch('retrovue.cli.commands.source.session') as mock_session:
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_importer = MagicMock(); mock_importer.name = 'PlexImporter'
        with patch('retrovue.usecases.source_add.add_source') as mock_add, \
             patch('retrovue.cli.commands.source.get_importer', return_value=mock_importer):
            mock_add.return_value = {
                'id': 'id',
                'external_id': 'plex-12345678',
                'name': 'Test Plex',
                'type': 'plex',
                'config': {'servers': [{'base_url': 'http://test', 'token': 't'}]},
                'enrichers': []
            }
            res = runner.invoke(app, ['source','add','--type','plex','--name','Test Plex','--base-url','http://test','--token','t','--json'])
            print('exit_code:', res.exit_code)
            print('STDOUT:\n', res.stdout)
            print('STDERR:\n', res.stderr)

if __name__ == '__main__':
    main()


