from module.model import BertCLIPModel
from transformers import (
    CLIPConfig,
    BertModel,
    CLIPFeatureExtractor,
    CLIPProcessor,
    BertTokenizerFast,
    HfArgumentParser,
    TrainingArguments,
    set_seed,
    Trainer,
)
from loguru import logger
from module.dataset import CLIPDataset
from module.argument import CLIPArguments
import argparse
import os
import json
from os.path import join
from module.datacollator import CLIPCollator


def load_model_and_processor(clip_pretrain_path, bert_pretrain_path):
    """
    加载模型和输入的processor
    :param clip_pretrain_path:
    :param bert_pretrain_path:
    :return:
    """
    # 加载bert模型
    bert_model = BertModel.from_pretrained(bert_pretrain_path)
    bert_config = bert_model.config
    # 加载clip模型
    clip_config = CLIPConfig.from_pretrained(clip_pretrain_path)
    clip_config.text_config = bert_config   # CLIPConfig中的text_config默认是CLIPTextConfig，将其修改为BertConfig
    # 忽略不匹配的预训练权重，主要是由于text_encoder更换为了bert
    bert_clip_model = BertCLIPModel.from_pretrained(clip_pretrain_path, config=clip_config, ignore_mismatched_sizes=True)
    # 更新clip的text encoder更新为bert的模型权重
    setattr(bert_clip_model, 'text_model', bert_model)
    # 将vision_model的权重冻结
    for name, param in bert_clip_model.vision_model.named_parameters():
            param.requires_grad = False

    # 查看clip中的bert是否设置正确
    logger.info(
        'bert_clip_model data_ptr:{}'.format(bert_clip_model.text_model.embeddings.word_embeddings.weight.data_ptr()))
    logger.info('bert data_ptr:{}'.format(bert_model.embeddings.word_embeddings.weight.data_ptr()))

    # 加载feature_extractor和tokenizer
    feature_extractor = CLIPFeatureExtractor.from_pretrained(clip_pretrain_path)
    tokenizer = BertTokenizerFast.from_pretrained(bert_pretrain_path)
    # note: 代码库默认使用CLIPTokenizer, 这里需要设置自己需要的tokenizer的名称
    CLIPProcessor.tokenizer_class = 'BertTokenizerFast'
    clip_processor = CLIPProcessor(feature_extractor=feature_extractor, tokenizer=tokenizer)

    return bert_clip_model, clip_processor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train_args_file", type=str, default='train_args/train_clip-bak.json', help="")
    args = parser.parse_args()
    train_args_file = args.train_args_file
    # 读取参数配置
    parser = HfArgumentParser((CLIPArguments, TrainingArguments))
    args, training_args = parser.parse_json_file(json_file=train_args_file)
    # 创建输出目录
    if not os.path.exists(training_args.output_dir):
        os.makedirs(training_args.output_dir)
    # 记录训练参数
    with open(train_args_file, 'r', encoding='utf8') as f:
        train_args = json.load(f)
    with open(join(training_args.output_dir, 'train_args.json'), 'w', encoding='utf8') as f:
        json.dump(train_args, f, indent=2)
    # 设置随机种子
    set_seed(training_args.seed)
    # 加载模型和处理器
    bert_clip_model, clip_processor = load_model_and_processor(args.clip_pretrain_path, args.bert_pretrain_path)
    # 加载数据集
    train_dataset = CLIPDataset(args.train_file, clip_processor)
    test_dataset = CLIPDataset(args.test_file, clip_processor)
    # 初始化collator
    data_collator = CLIPCollator(clip_processor=clip_processor, max_seq_length=args.max_seq_length)

    # 初始化训练器
    # 此处将tokenizer设为clip_processor，主要是为了保存模型的时候能够顺便保存processor的配置，没有其他作用。
    trainer = Trainer(
        model=bert_clip_model,
        args=training_args,
        train_dataset=train_dataset,
        data_collator=data_collator,
        tokenizer=clip_processor
    )

    # 开始训练
    train_result = trainer.train()
    metrics = train_result.metrics
    trainer.log_metrics("train", metrics)
    trainer.save_metrics("train", metrics)
    trainer.save_state()
    trainer.save_model(join(train_args.output_dir, 'checkpoint-final'))

    # 评测验证集的指标
    logger.info("*** Evaluate ***")
    metrics = trainer.evaluate(test_dataset)
    trainer.log_metrics("eval", metrics)
    trainer.save_metrics("eval", metrics)


if __name__ == '__main__':
    main()