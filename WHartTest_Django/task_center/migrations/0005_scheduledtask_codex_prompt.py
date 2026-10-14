from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('task_center', '0004_remove_executing_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='scheduledtask',
            name='codex_prompt',
            field=models.TextField(
                blank=True,
                default='',
                help_text='模块为 Codex 实现时，交给本机 Codex CLI 的目标说明',
                verbose_name='Codex 任务说明',
            ),
        ),
    ]
