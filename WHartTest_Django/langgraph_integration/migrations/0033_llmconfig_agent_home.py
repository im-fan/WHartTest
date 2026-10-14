from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('langgraph_integration', '0032_chatmessage_unique_session_chat_message'),
    ]

    operations = [
        migrations.AddField(
            model_name='llmconfig',
            name='agent_home',
            field=models.CharField(
                blank=True,
                default='',
                help_text='本地 Agent 的配置目录。Codex 默认 ~/.codex',
                max_length=512,
                verbose_name='Agent Home',
            ),
        ),
        migrations.AlterField(
            model_name='llmconfig',
            name='api_url',
            field=models.URLField(
                blank=True,
                default='',
                help_text='LLM服务的API端点URL。Codex 等本地 Agent 可留空',
                verbose_name='API地址',
            ),
        ),
        migrations.AlterField(
            model_name='llmconfig',
            name='provider',
            field=models.CharField(
                choices=[
                    ('openai_compatible', 'OpenAI 兼容'),
                    ('deepseek', 'DeepSeek'),
                    ('qwen', 'Qwen/通义千问'),
                    ('codex', 'Codex'),
                ],
                default='openai_compatible',
                help_text='LLM服务供应商',
                max_length=50,
                verbose_name='供应商',
            ),
        ),
    ]
