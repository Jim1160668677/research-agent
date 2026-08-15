"""内置插件种子数据 - 预置生物信息学工具插件市场清单

新增市场字段:
- install_method: 一键部署方式 (conda/pip/binary/manual)
- os_compatibility: 平台兼容
- homepage / docs_url / support_email: 技术支持渠道
- latest_version: 市场最新版本 (用于更新检测)
- version_history: 版本历史 (写入 plugin_versions 表)
- downloads / rating: 初始市场数据
"""

# 通用工具 (依赖节点)
GENERIC_TOOLS = {
    "java": {
        "name": "java", "version": "17.0.8", "description": "Java 运行时环境，Trimmomatic 等工具的运行依赖",
        "author": "Oracle", "category": "runtime", "tags": ["runtime", "jvm"],
        "license": "GPL-2.0", "source_url": "https://www.oracle.com/java/",
        "homepage": "https://www.oracle.com/java/", "docs_url": "https://docs.oracle.com/en/java/",
        "support_email": "", "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "manual", "probe": {"command": "java", "args": ["-version"]}},
        "dependencies": [],
    },
    "r": {
        "name": "r", "version": "4.3.2", "description": "R 统计计算环境，生物信息学分析的基础运行时",
        "author": "R Core Team", "category": "runtime", "tags": ["runtime", "statistics"],
        "license": "GPL-2.0", "source_url": "https://www.r-project.org/",
        "homepage": "https://www.r-project.org/", "docs_url": "https://cran.r-project.org/manuals.html",
        "support_email": "", "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "conda", "package": "r-base", "channel": "conda-forge",
                           "probe": {"command": "R", "args": ["--version"]}},
        "dependencies": [],
    },
    "bioconductor": {
        "name": "bioconductor", "version": "3.18.0", "description": "生物信息学 R 软件包生态",
        "author": "Bioconductor Team", "category": "runtime", "tags": ["r", "bioconductor"],
        "license": "Artistic-2.0", "source_url": "https://www.bioconductor.org/",
        "homepage": "https://www.bioconductor.org/",
        "docs_url": "https://www.bioconductor.org/help/",
        "support_email": "", "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "conda", "package": "bioconductor-biocinstaller", "channel": "bioconda",
                           "probe": {"command": "R", "args": ["-e", "\"requireNamespace('BiocManager')\""]}},
        "dependencies": [{"name": "r", "version": ">=4.0"}],
    },
    "subread": {
        "name": "subread", "version": "2.0.6", "description": "Subread 比对与计数套件",
        "author": "Wei Shi Lab", "category": "alignment", "tags": ["alignment", "counts"],
        "license": "GPL-3.0", "source_url": "https://subread.sourceforge.net/",
        "homepage": "https://subread.sourceforge.net/", "docs_url": "https://subread.sourceforge.net/SubreadUsersGuide.pdf",
        "support_email": "", "os_compatibility": ["linux", "macos"],
        "install_method": {"method": "conda", "package": "subread", "channel": "bioconda",
                           "probe": {"command": "featureCounts", "args": ["-v"]}},
        "dependencies": [],
    },
    "htslib": {
        "name": "htslib", "version": "1.19", "description": "高通量测序数据文件格式处理库 (SAM/BAM/CRAM/VCF)",
        "author": "samtools team", "category": "runtime", "tags": ["library", "bam"],
        "license": "MIT", "source_url": "https://github.com/samtools/htslib",
        "homepage": "https://www.htslib.org/", "docs_url": "https://www.htslib.org/doc/",
        "support_email": "", "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "conda", "package": "htslib", "channel": "bioconda",
                           "probe": {"command": "tabix", "args": ["--version"]}},
        "dependencies": [],
    },
    "mgltools": {
        "name": "mgltools", "version": "1.5.7", "description": "分子图形工具集，含 AutoDockTools (PDBQT准备)",
        "author": "Scripps Research", "category": "docking", "tags": ["molecular", "prep"],
        "license": "Various", "source_url": "https://ccsb.scripps.edu/mgltools/",
        "homepage": "https://ccsb.scripps.edu/mgltools/", "docs_url": "https://ccsb.scripps.edu/mgltools/documentation/",
        "support_email": "", "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "manual",
                           "probe": {"command": "pythonsh", "args": ["-h"]}},
        "dependencies": [],
    },
    "maestro": {
        "name": "maestro", "version": "2024-2", "description": "Schrödinger 主控平台，Glide 的必需运行环境",
        "author": "Schrödinger, LLC", "category": "docking", "tags": ["commercial", "platform"],
        "license": "Commercial", "source_url": "https://www.schrodinger.com/platform/products/maestro/",
        "homepage": "https://www.schrodinger.com/platform/products/maestro/",
        "docs_url": "https://www.schrodinger.com/platform/products/maestro/",
        "support_email": "help@schrodinger.com",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "manual", "probe": {"command": "maestro", "args": ["-version"]}},
        "dependencies": [],
    },
}

# 主工具清单
BUILTIN_PLUGINS = [
    {
        "name": "fastqc",
        "version": "0.12.1",
        "latest_version": "0.12.1",
        "description": "高通量测序数据质量控制工具，生成HTML质量控制报告",
        "author": "Babraham Institute",
        "category": "quality_control",
        "tags": ["qc", "fastq", "sequencing"],
        "license": "GPL-3.0",
        "source_url": "https://github.com/s-andrews/FastQC",
        "homepage": "https://www.bioinformatics.babraham.ac.uk/projects/fastqc/",
        "docs_url": "https://www.bioinformatics.babraham.ac.uk/projects/fastqc/Help/",
        "support_email": "simon.andrews@babraham.ac.uk",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "conda", "package": "fastqc", "channel": "bioconda",
                           "probe": {"command": "fastqc", "args": ["--version"]}},
        "smoke_tests": [
            {"id": "version", "command": "fastqc", "args": ["--version"],
             "expect_exit": 0, "expect_stdout": "FastQC", "timeout_s": 60},
        ],
        "downloads": 1280, "rating_avg": 4.7, "rating_count": 86,
        "dependencies": [],
        "version_history": [
            {"version": "0.11.9", "release_date": "2021-02-01", "size_mb": 2.5,
             "changelog": "修复报告生成问题，增强多平台兼容"},
            {"version": "0.12.1", "release_date": "2023-12-15", "size_mb": 2.8,
             "changelog": "新增overlap模块，改进HTML报告界面", "is_latest": True},
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "threads": {"type": "integer", "default": 4},
                "output_dir": {"type": "string"},
            },
        },
    },
    {
        "name": "trimmomatic",
        "version": "0.39",
        "latest_version": "0.39",
        "description": "Illumina测序数据修剪工具，支持接头切除和低质量碱基过滤",
        "author": "Usadel Lab",
        "category": "preprocessing",
        "tags": ["trimming", "fastq", "adapters"],
        "license": "GPL-3.0",
        "source_url": "https://github.com/usadellab/Trimmomatic",
        "homepage": "http://www.usadellab.org/cms/?page=trimmomatic",
        "docs_url": "http://www.usadellab.org/cms/uploads/supplementary/Trimmomatic/TrimmomaticManual_V0.32.pdf",
        "support_email": "bolger@bioi.uni-freiburg.de",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "conda", "package": "trimmomatic", "channel": "bioconda",
                           "probe": {"command": "trimmomatic", "args": ["-version"]}},
        "downloads": 954, "rating_avg": 4.5, "rating_count": 62,
        "dependencies": [{"name": "java", "version": ">=8"}],
        "version_history": [
            {"version": "0.38", "release_date": "2019-01-01", "size_mb": 0.4,
             "changelog": "性能改进，修复CROP边界问题"},
            {"version": "0.39", "release_date": "2020-06-15", "size_mb": 0.4,
             "changelog": "新增ILLUMINACLIP改进，支持更多平台", "is_latest": True},
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "illuminaclip": {"type": "string", "default": "2:30:10"},
                "leading": {"type": "integer", "default": 3},
                "trailing": {"type": "integer", "default": 3},
            },
        },
    },
    {
        "name": "bwa",
        "version": "0.7.17",
        "latest_version": "0.7.17",
        "description": "Burrows-Wheeler比对工具，快速将reads比对到参考基因组",
        "author": "Heng Li",
        "category": "alignment",
        "tags": ["alignment", "mapping", "dna-seq"],
        "license": "GPL-3.0",
        "source_url": "https://github.com/lh3/bwa",
        "homepage": "https://bio-bwa.sourceforge.net/",
        "docs_url": "https://bio-bwa.sourceforge.net/bwa.shtml",
        "support_email": "",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "conda", "package": "bwa", "channel": "bioconda",
                           "probe": {"command": "bwa", "args": ["2>&1 | head -1"]}},
        "downloads": 1567, "rating_avg": 4.8, "rating_count": 103,
        "dependencies": [],
        "version_history": [
            {"version": "0.7.12", "release_date": "2015-01-01", "size_mb": 1.5,
             "changelog": "经典稳定版本"},
            {"version": "0.7.17", "release_date": "2017-10-23", "size_mb": 1.6,
             "changelog": "修复BWA-MEM长读长问题，改进性能", "is_latest": True},
        ],
        "config_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "samtools",
        "version": "1.19",
        "latest_version": "1.21",
        "description": "SAM/BAM/CRAM格式处理工具套件，支持排序、索引、统计",
        "author": "samtools team",
        "category": "alignment",
        "tags": ["bam", "sam", "alignment", "utility"],
        "license": "MIT",
        "source_url": "https://github.com/samtools/samtools",
        "homepage": "https://www.htslib.org/",
        "docs_url": "https://www.htslib.org/doc/samtools.html",
        "support_email": "samtools-help@lists.sourceforge.net",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "conda", "package": "samtools", "channel": "bioconda",
                           "probe": {"command": "samtools", "args": ["--version"]}},
        "smoke_tests": [
            {"id": "version", "command": "samtools", "args": ["--version"],
             "expect_exit": 0, "expect_stdout": "samtools", "timeout_s": 60},
        ],
        "downloads": 2104, "rating_avg": 4.9, "rating_count": 148,
        "dependencies": [{"name": "htslib", "version": ">=1.19"}],
        "version_history": [
            {"version": "1.17", "release_date": "2023-02-01", "size_mb": 3.2,
             "changelog": "支持更高效的索引"},
            {"version": "1.19", "release_date": "2023-10-15", "size_mb": 3.4,
             "changelog": "修复CRAM编码问题，新增工具命令"},
            {"version": "1.21", "release_date": "2024-12-01", "size_mb": 3.6,
             "changelog": "性能优化，修复内存泄漏", "is_latest": True},
        ],
        "config_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "hisat2",
        "version": "2.2.1",
        "latest_version": "2.2.1",
        "description": "转录组比对工具，支持RNA-seq splice-aware比对",
        "author": "Kim Lab",
        "category": "alignment",
        "tags": ["rna-seq", "spliced", "alignment"],
        "license": "GPL-3.0",
        "source_url": "https://github.com/DaehwanKimLab/hisat2",
        "homepage": "https://daehwankimlab.github.io/hisat2/",
        "docs_url": "https://daehwankimlab.github.io/hisat2/manual/",
        "support_email": "",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "conda", "package": "hisat2", "channel": "bioconda",
                           "probe": {"command": "hisat2", "args": ["--version"]}},
        "downloads": 1120, "rating_avg": 4.6, "rating_count": 78,
        "dependencies": [],
        "version_history": [
            {"version": "2.1.0", "release_date": "2019-07-01", "size_mb": 12.0,
             "changelog": "初始稳定版本"},
            {"version": "2.2.1", "release_date": "2021-01-01", "size_mb": 12.5,
             "changelog": "改进多线程比对性能", "is_latest": True},
        ],
        "config_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "featurecounts",
        "version": "2.0.6",
        "latest_version": "2.0.6",
        "description": "read计数工具，统计比对reads在各基因上的数量",
        "author": "Liao et al.",
        "category": "quantification",
        "tags": ["counts", "expression", "rna-seq"],
        "license": "GPL-3.0",
        "source_url": "https://subread.sourceforge.net/",
        "homepage": "https://subread.sourceforge.net/",
        "docs_url": "https://subread.sourceforge.net/SubreadUsersGuide.pdf",
        "support_email": "",
        "os_compatibility": ["linux", "macos"],
        "install_method": {"method": "conda", "package": "subread", "channel": "bioconda",
                           "probe": {"command": "featureCounts", "args": ["-v"]}},
        "downloads": 892, "rating_avg": 4.5, "rating_count": 55,
        "dependencies": [{"name": "subread", "version": ">=2.0"}],
        "version_history": [
            {"version": "2.0.1", "release_date": "2020-06-01", "size_mb": 45.0,
             "changelog": "支持更多注释格式"},
            {"version": "2.0.6", "release_date": "2023-05-15", "size_mb": 46.0,
             "changelog": "修复多线程计数错误", "is_latest": True},
        ],
        "config_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "kallisto",
        "version": "0.50.1",
        "latest_version": "0.50.1",
        "description": "伪比对定量工具，快速进行转录本定量",
        "author": "Pachter Lab",
        "category": "quantification",
        "tags": ["pseudoalignment", "rna-seq", "fast"],
        "license": "BSD-2-Clause",
        "source_url": "https://github.com/pachterlab/kallisto",
        "homepage": "https://pachterlab.github.io/kallisto/",
        "docs_url": "https://pachterlab.github.io/kallisto/manual",
        "support_email": "",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "conda", "package": "kallisto", "channel": "bioconda",
                           "probe": {"command": "kallisto", "args": ["version"]}},
        "smoke_tests": [
            {"id": "version", "command": "kallisto", "args": ["version"],
             "expect_exit": 0, "expect_stdout": "kallisto", "timeout_s": 60},
        ],
        "downloads": 743, "rating_avg": 4.6, "rating_count": 49,
        "dependencies": [],
        "version_history": [
            {"version": "0.46.2", "release_date": "2021-05-01", "size_mb": 5.0,
             "changelog": "经典版本"},
            {"version": "0.50.1", "release_date": "2023-11-01", "size_mb": 5.2,
             "changelog": "性能大幅提升，新增可视化", "is_latest": True},
        ],
        "config_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "deseq2",
        "version": "1.42.0",
        "latest_version": "1.44.0",
        "description": "R语言差异表达分析包，基于负二项分布模型",
        "author": "Love, Huber, Anders",
        "category": "differential_expression",
        "tags": ["de-analysis", "rna-seq", "r"],
        "license": "GPL-3.0",
        "source_url": "https://bioconductor.org/packages/release/bioc/html/DESeq2.html",
        "homepage": "https://bioconductor.org/packages/DESeq2",
        "docs_url": "https://bioconductor.org/packages/release/bioc/vignettes/DESeq2/inst/doc/DESeq2.html",
        "support_email": "michaelisaiahlove@gmail.com",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "conda", "package": "bioconductor-deseq2", "channel": "bioconda",
                           "probe": {"command": "R", "args": ["-e", "\"requireNamespace('DESeq2')\""]}},
        "downloads": 1321, "rating_avg": 4.8, "rating_count": 92,
        "dependencies": [{"name": "r", "version": ">=4.0"}, {"name": "bioconductor", "version": ">=3.15"}],
        "version_history": [
            {"version": "1.40.0", "release_date": "2023-04-01", "size_mb": 3.0,
             "changelog": "适配Bioconductor 3.17"},
            {"version": "1.42.0", "release_date": "2023-10-25", "size_mb": 3.1,
             "changelog": "适配Bioconductor 3.18, 修复lfcShrink"},
            {"version": "1.44.0", "release_date": "2024-10-29", "size_mb": 3.2,
             "changelog": "适配Bioconductor 3.19, 性能改进", "is_latest": True},
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "padj_threshold": {"type": "number", "default": 0.05},
                "log2fc_threshold": {"type": "number", "default": 1.0},
            },
        },
    },
    {
        "name": "cutadapt",
        "version": "4.5",
        "latest_version": "4.9",
        "description": "通用序列修剪工具，支持各种NGS数据",
        "author": "Marcel Martin",
        "category": "preprocessing",
        "tags": ["trimming", "adapters"],
        "license": "MIT",
        "source_url": "https://github.com/marcelm/cutadapt",
        "homepage": "https://cutadapt.readthedocs.io/",
        "docs_url": "https://cutadapt.readthedocs.io/en/stable/",
        "support_email": "",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "pip", "package": "cutadapt",
                           "probe": {"command": "cutadapt", "args": ["--version"]}},
        "downloads": 688, "rating_avg": 4.5, "rating_count": 44,
        "dependencies": [],
        "version_history": [
            {"version": "4.1", "release_date": "2022-03-01", "size_mb": 0.4,
             "changelog": "新增双端自适应修剪"},
            {"version": "4.5", "release_date": "2023-05-01", "size_mb": 0.5,
             "changelog": "改进PE模式，性能优化"},
            {"version": "4.9", "release_date": "2024-12-05", "size_mb": 0.5,
             "changelog": "新增损坏序列检测", "is_latest": True},
        ],
        "config_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "bowtie2",
        "version": "2.5.3",
        "latest_version": "2.5.4",
        "description": "快速灵敏的短序列比对工具",
        "author": "Langmead Lab",
        "category": "alignment",
        "tags": ["alignment", "short-reads"],
        "license": "GPL-3.0",
        "source_url": "https://github.com/BenLangmead/bowtie2",
        "homepage": "https://bowtie-bio.sourceforge.net/bowtie2/",
        "docs_url": "https://bowtie-bio.sourceforge.net/bowtie2/manual.shtml",
        "support_email": "",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "conda", "package": "bowtie2", "channel": "bioconda",
                           "probe": {"command": "bowtie2", "args": ["--version"]}},
        "downloads": 1055, "rating_avg": 4.7, "rating_count": 71,
        "dependencies": [],
        "version_history": [
            {"version": "2.4.5", "release_date": "2022-01-01", "size_mb": 8.0,
             "changelog": "经典版本"},
            {"version": "2.5.3", "release_date": "2023-12-01", "size_mb": 8.4,
             "changelog": "支持新的索引格式"},
            {"version": "2.5.4", "release_date": "2024-06-01", "size_mb": 8.4,
             "changelog": "修复C++20编译问题", "is_latest": True},
        ],
        "config_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "stringtie",
        "version": "2.2.1",
        "latest_version": "2.2.3",
        "description": "转录本组装和定量工具",
        "author": "Pertea Lab",
        "category": "transcriptome",
        "tags": ["assembly", "transcripts", "quantification"],
        "license": "MIT",
        "source_url": "https://github.com/gpertea/stringtie",
        "homepage": "https://ccb.jhu.edu/software/stringtie/",
        "docs_url": "https://ccb.jhu.edu/software/stringtie/index.shtml?t=manual",
        "support_email": "gpertea@jhu.edu",
        "os_compatibility": ["linux", "macos"],
        "install_method": {"method": "conda", "package": "stringtie", "channel": "bioconda",
                           "probe": {"command": "stringtie", "args": ["--version"]}},
        "downloads": 690, "rating_avg": 4.4, "rating_count": 47,
        "dependencies": [],
        "version_history": [
            {"version": "2.2.1", "release_date": "2022-05-01", "size_mb": 2.0,
             "changelog": "经典版本"},
            {"version": "2.2.3", "release_date": "2024-01-15", "size_mb": 2.1,
             "changelog": "修复长读长启动子检测", "is_latest": True},
        ],
        "config_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "fastp",
        "version": "0.23.4",
        "latest_version": "0.24.0",
        "description": "一体化FASTQ预处理工具，质控+修剪+过滤",
        "author": "OpenGene",
        "category": "quality_control",
        "tags": ["qc", "trimming", "fast"],
        "license": "MIT",
        "source_url": "https://github.com/OpenGene/fastp",
        "homepage": "https://github.com/OpenGene/fastp",
        "docs_url": "https://github.com/OpenGene/fastp#user-guide",
        "support_email": "shifu.chen@outlook.com",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "conda", "package": "fastp", "channel": "bioconda",
                           "probe": {"command": "fastp", "args": ["--version"]}},
        "downloads": 1120, "rating_avg": 4.7, "rating_count": 83,
        "dependencies": [],
        "version_history": [
            {"version": "0.23.2", "release_date": "2022-06-01", "size_mb": 1.2,
             "changelog": "修复PE模式bug"},
            {"version": "0.23.4", "release_date": "2023-10-01", "size_mb": 1.2,
             "changelog": "新增UMI处理"},
            {"version": "0.24.0", "release_date": "2024-09-01", "size_mb": 1.3,
             "changelog": "性能提升30%", "is_latest": True},
        ],
        "config_schema": {"type": "object", "properties": {}},
    },
    # ===== 分子对接软件 =====
    {
        "name": "autodock_vina",
        "version": "1.2.5",
        "latest_version": "1.2.5",
        "description": "开源分子对接软件，预测配体与受体的结合模式和结合能",
        "author": "Scripps Research",
        "category": "docking",
        "tags": ["docking", "molecular", "drug-discovery"],
        "license": "GPL",
        "source_url": "https://github.com/ccsb-scripps/AutoDock-Vina",
        "homepage": "https://vina.scripps.edu/",
        "docs_url": "https://autodock-vina.readthedocs.io/",
        "support_email": "vina@scripps.edu",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "conda", "package": "autodock-vina", "channel": "conda-forge",
                           "probe": {"command": "vina", "args": ["--version"]}},
        "downloads": 1895, "rating_avg": 4.8, "rating_count": 134,
        "dependencies": [{"name": "mgltools", "version": ">=1.5.7"}],
        "version_history": [
            {"version": "1.1.2", "release_date": "2011-03-01", "size_mb": 5.0,
             "changelog": "经典版本，遗传算法优化"},
            {"version": "1.2.3", "release_date": "2021-08-01", "size_mb": 6.5,
             "changelog": "新增共价对接、双线程"},
            {"version": "1.2.5", "release_date": "2023-03-15", "size_mb": 7.0,
             "changelog": "性能提升，修复得分函数问题", "is_latest": True},
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "executable": {"type": "string", "default": "vina"},
                "exhaustiveness": {"type": "integer", "default": 8},
            },
        },
    },
    {
        "name": "glide",
        "version": "2024-2",
        "latest_version": "2024-2",
        "description": "Schrödinger高精度分子对接软件，支持SP/XP/HTVS精度与共价对接",
        "author": "Schrödinger, LLC",
        "category": "docking",
        "tags": ["docking", "commercial", "precision"],
        "license": "Commercial",
        "source_url": "https://www.schrodinger.com/platform/products/glide/",
        "homepage": "https://www.schrodinger.com/platform/products/glide/",
        "docs_url": "https://www.schrodinger.com/platform/products/glide/",
        "support_email": "help@schrodinger.com",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "manual",
                           "probe": {"command": "glide", "args": ["-version"]}},
        "downloads": 342, "rating_avg": 4.6, "rating_count": 41,
        "dependencies": [{"name": "maestro", "version": ">=2024-1"}],
        "version_history": [
            {"version": "2023-3", "release_date": "2023-06-01", "size_mb": 1200.0,
             "changelog": "增强共价对接"},
            {"version": "2024-2", "release_date": "2024-04-01", "size_mb": 1250.0,
             "changelog": "支持诱导契合新算法", "is_latest": True},
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "executable": {"type": "string", "default": "glide"},
                "precision": {"type": "string", "default": "SP"},
            },
        },
    },
    {
        "name": "gold",
        "version": "2024.2",
        "latest_version": "2024.2",
        "description": "CCDC遗传算法分子对接软件，支持柔性侧链与共价对接",
        "author": "Cambridge Crystallographic Data Centre",
        "category": "docking",
        "tags": ["docking", "genetic-algorithm", "commercial"],
        "license": "Commercial",
        "source_url": "https://www.ccdc.cam.ac.uk/solutions/software/gold/",
        "homepage": "https://www.ccdc.cam.ac.uk/solutions/software/gold/",
        "docs_url": "https://www.ccdc.cam.ac.uk/support/documentation/gold/",
        "support_email": "support@ccdc.cam.ac.uk",
        "os_compatibility": ["windows", "linux"],
        "install_method": {"method": "manual",
                           "probe": {"command": "gold", "args": ["-version"]}},
        "downloads": 298, "rating_avg": 4.5, "rating_count": 33,
        "dependencies": [],
        "version_history": [
            {"version": "2023.1", "release_date": "2023-01-01", "size_mb": 900.0,
             "changelog": "增强蛋白准备"},
            {"version": "2024.2", "release_date": "2024-05-01", "size_mb": 950.0,
             "changelog": "改进遗传算法参数", "is_latest": True},
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "executable": {"type": "string", "default": "gold"},
            },
        },
    },
    # ===== 蛋白质结构软件 =====
    {
        "name": "pymol",
        "version": "2.6.0",
        "latest_version": "2.6.0",
        "description": "分子可视化软件，支持高质量结构渲染、突变分析与轨迹展示",
        "author": "Schrödinger, LLC",
        "category": "structure",
        "tags": ["visualization", "structure", "render"],
        "license": "Open-Source/Commercial",
        "source_url": "https://pymol.org",
        "homepage": "https://pymol.org/",
        "docs_url": "https://pymol.org/dokuwiki/",
        "support_email": "help@schrodinger.com",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "conda", "package": "pymol-open-source", "channel": "conda-forge",
                           "probe": {"command": "pymol", "args": ["-c"]}},
        "downloads": 2130, "rating_avg": 4.9, "rating_count": 176,
        "dependencies": [],
        "version_history": [
            {"version": "2.5.0", "release_date": "2022-05-01", "size_mb": 180.0,
             "changelog": "新增多状态动画改进"},
            {"version": "2.6.0", "release_date": "2024-01-01", "size_mb": 190.0,
             "changelog": "全新UI，集成更多渲染插件", "is_latest": True},
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "executable": {"type": "string", "default": "pymol"},
            },
        },
    },
    {
        "name": "chimerax",
        "version": "1.8",
        "latest_version": "1.9",
        "description": "UCSF现代分子可视化软件，支持集成密度图、结构比较、序列分析",
        "author": "UCSF RBVI",
        "category": "structure",
        "tags": ["visualization", "structure", "density-map"],
        "license": "Open Source",
        "source_url": "https://www.cgl.ucsf.edu/chimerax/",
        "homepage": "https://www.cgl.ucsf.edu/chimerax/",
        "docs_url": "https://www.cgl.ucsf.edu/chimerax/docs/user/index.html",
        "support_email": "chimerax-users@cgl.ucsf.edu",
        "os_compatibility": ["windows", "linux", "macos"],
        "install_method": {"method": "manual",
                           "probe": {"command": "chimerax", "args": ["--version"]}},
        "downloads": 876, "rating_avg": 4.8, "rating_count": 64,
        "dependencies": [],
        "version_history": [
            {"version": "1.7", "release_date": "2023-06-01", "size_mb": 400.0,
             "changelog": "新增map锐化工具"},
            {"version": "1.8", "release_date": "2024-03-01", "size_mb": 420.0,
             "changelog": "增强GPU渲染"},
            {"version": "1.9", "release_date": "2025-01-15", "size_mb": 430.0,
             "changelog": "新增ALPHAFOLD集成", "is_latest": True},
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "executable": {"type": "string", "default": "chimerax"},
            },
        },
    },
    {
        "name": "swiss_pdbviewer",
        "version": "4.1.0",
        "latest_version": "4.1.0",
        "description": "Swiss-PdbViewer蛋白质结构分析工具，支持结构比对、突变建模、氢键分析",
        "author": "SIB Swiss Institute of Bioinformatics",
        "category": "structure",
        "tags": ["visualization", "analysis", "alignment"],
        "license": "Freeware",
        "source_url": "https://spdbv.unil.ch/",
        "homepage": "https://spdbv.unil.ch/",
        "docs_url": "https://spdbv.unil.ch/doc/memberhelp/spdbv/MainMenu.html",
        "support_email": "support@expasy.org",
        "os_compatibility": ["windows", "macos"],
        "install_method": {"method": "manual",
                           "probe": {"command": "spdbv", "args": ["-help"]}},
        "downloads": 412, "rating_avg": 4.2, "rating_count": 28,
        "dependencies": [],
        "version_history": [
            {"version": "4.1.0", "release_date": "2011-01-01", "size_mb": 15.0,
             "changelog": "经典稳定版本", "is_latest": True},
        ],
        "config_schema": {
            "type": "object",
            "properties": {
                "executable": {"type": "string", "default": "spdbv"},
            },
        },
    },
]

# 初始社区评价 (模拟种子评价)
SEED_REVIEWS = {
    "autodock_vina": [
        {"rating": 5, "comment": "开源免费，对接精度在标准数据集上表现优秀，文档完善。", "is_verified": True},
        {"rating": 4, "comment": "命令行好用，就是准备PDBQT需要额外工具。", "is_verified": True},
        {"rating": 5, "comment": "GPU版本速度快很多，推荐。", "is_verified": False},
    ],
    "glide": [
        {"rating": 5, "comment": "XP精度无出其右，商业化软件里体验最好的对接工具。", "is_verified": False},
        {"rating": 4, "comment": "精度高但许可证昂贵，需要Maestro环境。", "is_verified": True},
    ],
    "gold": [
        {"rating": 4, "comment": "遗传算法适合柔性对接，结果可靠。", "is_verified": True},
        {"rating": 5, "comment": "对金属蛋白的对接比其他软件好。", "is_verified": False},
    ],
    "pymol": [
        {"rating": 5, "comment": "渲染效果一流，脚本化能力强，科研绘图必备。", "is_verified": True},
        {"rating": 5, "comment": "从学习到发表论文，一直用它。", "is_verified": True},
        {"rating": 4, "comment": "开源版功能够用，商业版更顺手。", "is_verified": False},
    ],
    "chimerax": [
        {"rating": 5, "comment": "密度图可视化无敌，GPU渲染流畅。", "is_verified": True},
        {"rating": 4, "comment": "比老Chimera好用多了，序列分析集成好。", "is_verified": False},
    ],
    "swiss_pdbviewer": [
        {"rating": 4, "comment": "老牌软件，结构比对功能仍然实用。", "is_verified": True},
        {"rating": 3, "comment": "界面过时了，但突变建模功能简单直观。", "is_verified": False},
    ],
    "fastqc": [
        {"rating": 5, "comment": "质控报告的黄金标准。", "is_verified": True},
        {"rating": 4, "comment": "界面老但稳定。", "is_verified": False},
    ],
    "deseq2": [
        {"rating": 5, "comment": "差异表达分析首选，统计严谨。", "is_verified": True},
    ],
    "samtools": [
        {"rating": 5, "comment": "每天都要用的工具，转换排序一次搞定。", "is_verified": True},
    ],
    "bwa": [
        {"rating": 5, "comment": "比对速度和准确性平衡得最好。", "is_verified": True},
    ],
    "cutadapt": [
        {"rating": 4, "comment": "修剪接头灵活，配Li搜工具链好用。", "is_verified": False},
    ],
    "fastp": [
        {"rating": 5, "comment": "一条命令搞定质控和修剪，快！", "is_verified": True},
    ],
}

ALL_TOOLS = list(GENERIC_TOOLS.values()) + BUILTIN_PLUGINS


async def seed_plugins(session):
    """将内置插件种子数据写入数据库 (UPSERT 语义，可安全重复执行)"""
    from sqlalchemy import func, select
    from sqlalchemy import update as sa_update

    from ..core.models.db import Plugin, PluginReview, PluginVersion
    from .manifest import manifest_digest, manifest_from_plugin

    added = 0
    updated = 0

    for data in ALL_TOOLS:
        exists = await session.execute(
            select(Plugin).where(Plugin.name == data["name"])
        )
        plugin = exists.scalar_one_or_none()
        if not plugin:
            plugin = Plugin(
                name=data["name"],
                version=data["version"],
                latest_version=data.get("latest_version", data["version"]),
                description=data["description"],
                author=data.get("author"),
                category=data["category"],
                tags=data.get("tags", []),
                icon=data.get("icon"),
                license=data.get("license"),
                source_url=data.get("source_url"),
                homepage=data.get("homepage"),
                docs_url=data.get("docs_url"),
                support_email=data.get("support_email"),
                os_compatibility=data.get("os_compatibility", []),
                install_method=data.get("install_method", {"method": "manual"}),
                smoke_tests=data.get("smoke_tests", []),
                downloads=data.get("downloads", 0),
                rating_avg=data.get("rating_avg", 0.0),
                rating_count=data.get("rating_count", 0),
                dependencies=data.get("dependencies", []),
                config_schema=data.get("config_schema", {}),
                status="available",
                is_installed=False,
                source_registry="builtin",
                source_identifier=data["name"],
                trust_status="curated",
            )
            session.add(plugin)
            added += 1
            await session.flush()

        else:
            # 更新市场字段 (不覆盖用户安装状态)
            plugin.latest_version = data.get("latest_version", data["version"])
            plugin.description = data.get("description", plugin.description)
            plugin.homepage = data.get("homepage", plugin.homepage)
            plugin.docs_url = data.get("docs_url", plugin.docs_url)
            plugin.support_email = data.get("support_email", "")
            plugin.os_compatibility = data.get("os_compatibility", [])
            plugin.install_method = data.get("install_method", {"method": "manual"})
            if data.get("smoke_tests"):
                plugin.smoke_tests = data["smoke_tests"]
            if not plugin.downloads:
                plugin.downloads = data.get("downloads", 0)
            if not plugin.rating_avg:
                plugin.rating_avg = data.get("rating_avg", 0.0)
                plugin.rating_count = data.get("rating_count", 0)
            updated += 1
            await session.flush()

        plugin.source_registry = plugin.source_registry or "builtin"
        plugin.source_identifier = plugin.source_identifier or plugin.name
        plugin.trust_status = plugin.trust_status or "curated"
        capability_manifest = manifest_from_plugin(plugin)
        plugin.manifest_schema_version = capability_manifest.schema_version
        plugin.manifest = capability_manifest.model_dump(mode="json")
        plugin.manifest_digest = manifest_digest(capability_manifest)

        # 版本历史
        for vh in data.get("version_history", []):
            v_exists = await session.execute(
                select(PluginVersion).where(
                    PluginVersion.plugin_id == plugin.id,
                    PluginVersion.version == vh["version"],
                )
            )
            if v_exists.scalar_one_or_none() is None:
                session.add(PluginVersion(
                    plugin_id=plugin.id,
                    version=vh["version"],
                    release_date=vh.get("release_date"),
                    changelog=vh.get("changelog"),
                    size_mb=vh.get("size_mb"),
                    download_url=vh.get("download_url") or data.get("source_url"),
                    is_latest=bool(vh.get("is_latest")),
                ))

        # 同步最新版本标记
        await session.execute(
            sa_update(PluginVersion)
            .where(PluginVersion.plugin_id == plugin.id, PluginVersion.version == data.get("latest_version", data["version"]))
            .values(is_latest=True)
        )

        # 种子评价 (仅在无评价时)
        reviews = SEED_REVIEWS.get(data["name"], [])
        if reviews:
            rev_exists = await session.execute(
                select(PluginReview.id).where(PluginReview.plugin_id == plugin.id).limit(1)
            )
            if rev_exists.scalar_one_or_none() is None:
                for r in reviews:
                    session.add(PluginReview(
                        plugin_id=plugin.id,
                        rating=r["rating"],
                        comment=r["comment"],
                        is_verified=r.get("is_verified", False),
                    ))
                await session.flush()
                # 同步聚合评分字段 (种子数据以实际评价为准)
                agg = await session.execute(
                    select(func.avg(PluginReview.rating), func.count(PluginReview.id))
                    .where(PluginReview.plugin_id == plugin.id)
                )
                avg_val, cnt_val = agg.one()
                plugin.rating_avg = round(float(avg_val or 0), 2)
                plugin.rating_count = int(cnt_val or 0)

    await session.commit()
    if added:
        print(f"已添加 {added} 个工具到插件市场")
    else:
        print(f"插件市场已存在，更新 {updated} 个工具的市场信息")
    return added


__all__ = ["BUILTIN_PLUGINS", "GENERIC_TOOLS", "SEED_REVIEWS", "seed_plugins"]
