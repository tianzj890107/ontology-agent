# Eimosp Foundation File Service

统一文件存储服务，支持多存储后端（MinIO、本地文件系统），提供简洁易用的SDK。项目采用模块化设计，包含公共模块、核心业务模块、SDK模块、启动模块和演示应用等6个核心模块，提供完整的文件存储、管理、预览、分享等功能。

## 项目结构

```
eimosp-foundation-fileserver/
├── fileserver-common/              # 公共模块
│   └── 定义公共的Client接口、请求响应对象、统一响应格式(Result)等
├── fileserver-core/                # 核心业务模块
│   ├── biz/                        # 业务逻辑层
│   ├── dal/                        # 数据访问层
│   ├── storage/                    # 存储抽象层
│   └── common/                     # 核心通用类（枚举、工具类等）
├── fileserver-sdk/                 # 远程SDK模块
│   └── 提供远程调用模式的客户端实现，通过HTTP调用文件服务接口
├── fileserver-embedded/            # 嵌入式SDK模块
│   └── 提供嵌入到应用客户端的调用方式，直接调用core模块的服务
├── fileserver-starter/             # 启动模块
│   ├── controller/                 # REST API控制器（管理接口、SDK接口、代理接口）
│   ├── common/                     # 启动模块通用类（拦截器、过滤器）
│   └── FileServerStarterApplication.java  # 启动类
├── fileserver-demo-application/    # 演示应用模块
│   └── 模拟应用接入SDK的场景，演示如何使用远程SDK
├── docs/                           # 文档目录
│   └── html/                       # HTML测试页面
│       ├── presigned-upload-test.html    # 预签名上传测试页面
│       ├── presigned-download-test.html  # 预签名下载测试页面
│       └── share-test.html               # 分享功能测试页面
└── pom.xml                         # 父POM
```

## 技术栈

- **JDK**: 21
- **框架**: Spring Boot 3.2.0
- **ORM**: MyBatis-Plus 3.5.5
- **数据库**: MySQL 8.0.33、PostgreSQL 15.2
- **存储后端**: MinIO

## 架构设计

### 模块架构

项目采用模块化设计，各模块职责清晰，依赖关系明确：

```
┌───────────────────────────────────────────────────────┐
│                  fileserver-common                     │
│                     公共模块                           │
└───────────────────────────────────────────────────────┘
          ↑                  ↑                  ↑
          │                  │                  │
┌─────────┴─────┐  ┌────────┴────────┐  ┌─────┴─────────┐
│fileserver-core│  │ fileserver-sdk  │  │fileserver-    │
│   核心模块     │  │   远程SDK模块   ─────→│starter 启动模块│
└───────────────┘  └─────────────────┘  └───────────────┘
          ↑                               (HTTP调用)
          │
┌─────────┴─────────┐
│ fileserver-embedded│
│   嵌入式模块     │
└───────────────────┘
```

**模块说明：**

- **fileserver-common**：公共模块，定义统一的接口、请求/响应对象、响应格式，无业务依赖
- **fileserver-core**：核心业务模块，包含业务逻辑(biz)、数据访问(dal)、存储抽象(storage)
- **fileserver-sdk**：远程SDK模块，提供HTTP客户端实现和自动配置的Web接口
- **fileserver-embedded**：嵌入式SDK模块，提供嵌入到应用客户端的调用方式
- **fileserver-starter**：启动模块，包含REST API控制器、拦截器、过滤器等Web层组件

### 发布命令

- **1. 清理并编译**

```bash
mvn clean compile -DskipTests
```

- **2. 验证依赖**

```bash
mvn dependency:tree -pl fileserver-sdk
```

- **3. 发布 SNAPSHOT（开发版本）**

```bash
mvn deploy -pl fileserver-common,fileserver-sdk,fileserver-sdk-web-extra -am -DskipTests
```

- **4. 验证发布结果**
  - 访问：`http://jfrog.boulderaitech.com/artifactory/webapp/#/artifacts/browse/tree/General/maven_snapshot_local`

- **5. 当版本稳定时，发布 RELEASE**

```bash
mvn versions:set -DnewVersion=1.0.0
mvn deploy -pl fileserver-common,fileserver-sdk,fileserver-sdk-web-extra -am -DskipTests
mvn versions:set -DnewVersion=1.0.1-SNAPSHOT
```


### 多存储后端

服务端采用**工厂模式**和**策略模式**实现多存储后端支持，支持桶级存储配置：

#### 核心组件

1. **StorageFactory（存储工厂）**
   - 统一管理所有存储服务实现
   - 根据存储类型动态获取对应的存储服务

2. **StorageService<T>（存储服务接口）**
   - 定义统一的存储操作接口（桶操作、文件操作、预签名URL等）
   - 使用泛型`T extends StorageMetadata`支持不同存储后端的元数据

3. **StorageContext<T>（存储配置上下文）**
   - 封装存储配置和元数据
   - 提供统一的配置访问接口
   - 支持配置版本管理和缓存

#### 存储实现

- **MinioFileStorageServiceImpl** - MinIO对象存储实现
  - 支持客户端缓存（基于配置ID）
  - 支持SSL跳过验证配置
  - 支持预签名URL生成

- **LocalFileStorageServiceImpl** - 本地文件系统存储实现
  - 支持自定义存储路径
  - 支持文件元数据管理

#### 桶级存储配置

- 每个桶关联一个存储配置（`StorageConfig`）
- 支持同一服务使用多种存储方式
- 存储配置存储在数据库中，支持动态切换

### 认证授权架构

采用**AK/SK认证机制**，支持请求签名验证：

1. **签名算法**：HMAC-SHA256
2. **签名内容**：请求方法 + 请求路径 + 查询参数 + 请求体
3. **请求头格式**：`Authorization: Bearer {accessKey}:{signature}`
4. **权限验证**：
   - 账号状态验证（启用/禁用）
   - 桶权限验证（账号必须是桶的拥有者）

### 缓存架构

采用**多级缓存机制**，提升性能：

1. **账号缓存**：本地缓存账号信息，TTL过期，防止缓存穿透
2. **桶缓存**：本地缓存桶信息，TTL过期，防止缓存穿透
3. **存储配置上下文缓存**：缓存解析后的存储配置上下文
4. **MinIO客户端缓存**：根据存储配置ID缓存MinIO客户端，避免重复创建

## 功能特性

### 服务端功能

1. **账号管理** (`/admin/account`)
   - 创建账号（AK/SK认证凭证）
   - 查询账号详情
   - 分页查询账号列表（支持按账号名称、状态筛选）
   - 删除账号

2. **桶管理** (`/admin/bucket`)
   - 创建桶（指定存储配置和拥有者）
   - 更新桶信息
   - 查询桶详情
   - 分页查询桶列表（支持按桶名称、账号AK、存储配置筛选）
   - 删除桶

3. **存储配置管理** (`/admin/storage-config`)
   - 创建存储配置（支持MinIO、本地文件系统等）
   - 更新存储配置
   - 查询存储配置详情
   - 分页查询存储配置列表（支持按配置名称、存储类型、状态筛选）
   - 获取存储配置下拉选项
   - 删除存储配置

4. **文件管理（SDK接口）** (`/sdk`)
   - **上传文件** - 同步上传文件到指定桶（支持自动生成对象键）
   - **下载文件** - 支持断点续传（Range请求）
   - **删除文件** - 删除指定桶中的对象
   - **生成预签名上传URL** - 用于前端直传到存储服务上传文件
   - **生成预签名下载URL** - 用于前端直传从存储服务下载文件

5. **文件预览（代理接口）** (`/file/preview`)
   - 通过domain链接访问文件，用于浏览器直接展示文件（如图片预览）
   - 支持断点续传（Range请求）
   - 自动设置正确的Content-Type响应头

6. **多存储后端支持** ⭐
   - **MinIO** - 对象存储服务（支持客户端缓存、SSL跳过验证配置）
   - **本地文件系统** - 本地磁盘存储
   - **桶级配置** - 每个桶关联一个存储配置，支持同一服务使用多种存储方式

7. **文件分享功能** ⭐
   - **创建分享链接** - 支持公开、密码、Token三种分享模式
   - **分享链接访问** - 通过分享链接访问文件，支持预览和下载
   - **分享信息查询** - 查询分享链接的基本信息
   - **分享权限控制** - 支持有效期、访问次数、密码验证、Token验证

8. **认证授权**
   - **AK/SK认证** - 所有SDK请求使用HMAC-SHA256签名验证（Bearer Token格式）
   - **账号权限验证** - 验证账号状态（启用/禁用）
   - **桶权限验证** - 验证账号是否为桶的拥有者
   - **请求签名** - 对请求方法、路径、查询参数、请求体进行签名

9. **缓存管理**
   - **账号缓存** - 本地缓存账号信息，支持TTL过期和缓存穿透防护
   - **桶缓存** - 本地缓存桶信息，支持TTL过期和缓存穿透防护
   - **存储配置上下文缓存** - 缓存存储配置上下文，减少重复创建客户端
   - **MinIO客户端缓存** - 根据存储配置ID缓存MinIO客户端，避免每次请求创建新客户端


## API接口

### Admin管理接口

| 模块 | 接口路径 | 请求方法 | 功能描述 | 认证要求 |
|------|---------|---------|---------|---------|
| 账号管理 | `/admin/account/create` | POST | 创建账号（AK/SK） | 无需认证 |
| 账号管理 | `/admin/account/detail/{id}` | GET | 查询账号详情 | 无需认证 |
| 账号管理 | `/admin/account/page` | GET | 分页查询账号列表（支持按账号名称、状态筛选） | 无需认证 |
| 账号管理 | `/admin/account/delete/{id}` | DELETE | 删除账号 | 无需认证 |
| 桶管理 | `/admin/bucket/page` | GET | 分页查询桶列表（支持按桶名称、账号AK、存储配置筛选） | 无需认证 |
| 桶管理 | `/admin/bucket/create` | POST | 创建桶 | 无需认证 |
| 桶管理 | `/admin/bucket/update` | PUT | 更新桶信息 | 无需认证 |
| 桶管理 | `/admin/bucket/delete/{id}` | DELETE | 删除桶 | 无需认证 |
| 桶管理 | `/admin/bucket/detail/{id}` | GET | 查询桶详情 | 无需认证 |
| 存储配置管理 | `/admin/storage-config/options` | GET | 获取存储配置下拉选项（所有启用的配置） | 无需认证 |
| 存储配置管理 | `/admin/storage-config/page` | GET | 分页查询存储配置列表（支持按配置名称、存储类型、状态筛选） | 无需认证 |
| 存储配置管理 | `/admin/storage-config/create` | POST | 创建存储配置 | 无需认证 |
| 存储配置管理 | `/admin/storage-config/update` | PUT | 更新存储配置 | 无需认证 |
| 存储配置管理 | `/admin/storage-config/delete/{id}` | DELETE | 删除存储配置 | 无需认证 |
| 存储配置管理 | `/admin/storage-config/detail/{id}` | GET | 查询存储配置详情 | 无需认证 |

### SDK接口（`/sdk/*`）

| 接口路径 | 请求方法 | 功能描述 | 说明 |
|---------|---------|---------|------|
| `/sdk/presigned/upload` | GET | 生成预签名上传URL | 用于前端直传到存储服务上传文件，支持自定义过期时间（默认3600秒） |
| `/sdk/presigned/download` | GET | 生成预签名下载URL | 用于前端直传从存储服务下载文件，支持自定义过期时间（默认3600秒） |
| `/sdk/object/put` | POST | 上传对象到指定桶 | 支持自动生成对象键，通过MultipartFile上传文件 |
| `/sdk/object/get` | GET | 下载对象 | 支持断点续传（Range请求头），返回文件流和元数据 |
| `/sdk/object/delete` | POST | 删除对象 | 删除指定桶中的对象 |
| `/sdk/share/create` | POST | 创建分享链接 | 支持公开、密码、Token三种分享模式 |
| `/sdk/share/info` | GET | 获取分享信息 | 通过分享令牌获取分享链接的基本信息 |

**认证要求**：所有SDK接口需要使用AK/SK认证，请求头格式：`Authorization: Bearer {accessKey}:{signature}`

### 文件接口（`/file/*`）

| 接口路径 | 请求方法 | 功能描述 | 说明 |
|---------|---------|---------|------|
| `/file/preview/{bucketName}/**` | GET | 文件预览（代理访问） | 通过domain链接访问文件，用于浏览器直接展示文件（如图片预览），支持断点续传 |
| `/file/share/{shareToken}` | GET | 访问分享文件 | 通过分享链接访问文件，支持预览和下载 |
| `/file/share/{shareToken}/info` | GET | 获取分享信息（公开） | 获取分享链接的基本信息，用于展示分享页面 |
| `/file/share/{shareToken}/verify` | POST | 验证分享密码 | 密码模式下验证访问密码 |

**认证要求**：文件接口无需认证，可直接访问

**参数说明：**
- `bucketName`：桶名称（必填）
- `key` / `objectKey`：对象键，即文件路径（必填，上传时可选，不传则自动生成）
- `expire`：过期时间，单位秒（可选，默认3600秒）
- `file`：文件对象（上传时必填）
- `Range`：范围请求头，格式：`bytes=start-end`（下载时可选，用于断点续传）


## SDK接入

提供简洁易用的SDK接口，屏蔽底层实现细节，降低业务系统接入门槛。SDK采用模块化设计，支持两种使用方式：

### 1. 添加依赖

根据使用场景选择不同的依赖方式：

#### 方式一：仅后端调用（推荐用于服务端应用）

如果只需要在后端代码中调用SDK实现文件上传、下载等功能，预签名接口由业务客户端自己实现，只需引入核心SDK模块：

```xml
<dependency>
    <groupId>com.boulderaitech</groupId>
    <artifactId>fileserver-sdk</artifactId>
    <version>1.0.0-SNAPSHOT</version>
</dependency>
```

**使用场景**：
- 服务端应用直接调用SDK进行文件操作
- 需要自定义预签名URL接口的业务逻辑
- 不需要SDK提供的默认Web接口

**功能**：
- ✅ 文件上传（`putObject`）
- ✅ 文件下载（`getObject`）
- ✅ 生成预签名上传URL（`generatePreSignedPutUrl`）
- ✅ 生成预签名下载URL（`generatePreSignedGetUrl`）
- ❌ 不提供默认的Web接口

#### 方式二：扩展Web功能（推荐用于需要Web接口的应用）

如果需要SDK自动提供Web接口能力（预签名上传/下载URL、文件预览等），需要额外引入Web扩展模块：

```xml
<dependency>
    <groupId>com.boulderaitech</groupId>
    <artifactId>fileserver-sdk-web-extra</artifactId>
    <version>1.0.0-SNAPSHOT</version>
</dependency>
```

**使用场景**：
- 需要快速提供预签名URL的Web接口
- 需要文件预览功能（`/file/preview/{bucketName}/**`）
- 前端需要直接调用预签名接口

**功能**：
- ✅ 包含方式一的所有功能
- ✅ 自动提供Web接口：`GET /file/presigned/upload`
- ✅ 自动提供Web接口：`GET /file/presigned/download`
- ✅ 自动提供Web接口：`GET /file/preview/{bucketName}/**`（文件预览）

**注意**：
- `fileserver-sdk-web-extra` 会自动引入 `fileserver-sdk`，但建议显式声明两个依赖以便清晰管理
- SDK会自动引入 `fileserver-common` 模块，包含公共接口和请求/响应对象

### 2. 配置参数

在 `application.yml` 或 `application.properties` 中配置：

```yaml
fileserver:
  server-url: http://172.16.5.190:30366        # 文件服务端地址
  access-key: 1Ffu7AJ1P9PNJwbD                 # 访问密钥（AK）
  secret-key: ARMr9xjwtzc+SKVOEhu0QcobicrHjdFm # 密钥（SK）
  bucket-name: static                         # 默认桶名称
  connect-timeout: 5000                       # 连接超时时间（毫秒），默认5000
  read-timeout: 30000                         # 读取超时时间（毫秒），默认30000
  retry-enabled: false                        # 是否启用重试，默认false
  max-retry-count: 3                          # 最大重试次数，默认3
```

### 3. 客户端调用SDK方法

SDK支持两种使用方式：Spring Bean注入（推荐）和编程式创建。

#### 3.1 方式一：Spring Bean注入（推荐）

SDK通过Spring Boot自动配置，可以直接注入 `FileServerClient` 使用：

```java
import com.eimosp.fileserver.common.client.FileServerClient;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class FileService {

    @Autowired
    private FileServerClient fileServerClient;

    // 使用fileServerClient进行文件操作
}
```

#### 3.2 方式二：编程式创建

如果不想使用Spring Bean注入，可以编程式创建客户端：

```java
import com.eimosp.fileserver.sdk.RemoteFileServerClient;
import com.eimosp.fileserver.sdk.RemoteFileServerClientConfig;
import com.eimosp.fileserver.common.client.FileServerClient;

// 创建配置对象
RemoteFileServerClientConfig config = new RemoteFileServerClientConfig();
config.setServerUrl("http://localhost:8080");
config.setAccessKey("your-access-key");
config.setSecretKey("your-secret-key");
config.setBucketName("default-bucket");
config.setConnectTimeout(5000);
config.setReadTimeout(30000);
config.setRetryEnabled(false);
config.setMaxRetryCount(3);

// 创建客户端
FileServerClient fileServerClient = new RemoteFileServerClient(config);

// 使用客户端进行文件操作
```

**注意**：
- 编程式创建时，配置参数需要手动设置
- 如果使用Spring环境，推荐使用Bean注入方式，配置会自动从`application.yml`读取

#### 3.3 上传文件

```java
import com.eimosp.fileserver.common.request.PutObjectRequest;
import com.eimosp.fileserver.common.response.PutObjectResult;
import com.eimosp.fileserver.common.model.ObjectMetadata;
import java.io.InputStream;

// 方式1：使用InputStream上传
PutObjectRequest request = new PutObjectRequest(
    "bucket-name",                    // 桶名称
    "upload/test.jpg",                // 对象键（文件路径）
    inputStream                       // 文件输入流
);

// 设置文件元数据（可选）
ObjectMetadata metadata = new ObjectMetadata();
metadata.setContentType("image/jpeg");
metadata.setContentLength(fileSize);
metadata.setFilename("test.jpg");
request.setMetadata(metadata);

// 上传文件
PutObjectResult result = fileServerClient.putObject(request);
String fileUrl = result.getFileUrl();  // 获取文件访问URL
```

#### 3.4 下载文件

```java
import com.eimosp.fileserver.common.request.GetObjectRequest;
import com.eimosp.fileserver.common.response.GetObjectResult;
import java.io.InputStream;

// 构建下载请求
GetObjectRequest request = new GetObjectRequest(
    "bucket-name",                    // 桶名称
    "upload/test.jpg"                 // 对象键（文件路径）
);

// 下载文件
GetObjectResult result = fileServerClient.getObject(request);
InputStream inputStream = result.getInputStream();  // 获取文件流
String contentType = result.getContentType();      // 获取文件类型
Long contentLength = result.getContentLength();     // 获取文件大小
String filename = result.getFilename();            // 获取文件名
```

#### 3.5 生成预签名上传URL

```java
import com.eimosp.fileserver.common.request.GeneratePreSignedUrlRequest;
import com.eimosp.fileserver.common.response.GeneratePresignedUrlResult;

// 构建请求
GeneratePreSignedUrlRequest request = new GeneratePreSignedUrlRequest(
    "bucket-name",                    // 桶名称
    "upload/test.jpg",                // 对象键（文件路径）
    3600                              // 过期时间（秒）
);

// 生成预签名URL
GeneratePresignedUrlResult result = fileServerClient.generatePreSignedPutUrl(request);
String preSignedUrl = result.getPreSignedUrl();  // 预签名上传URL
String fileUrl = result.getFileUrl();            // 文件访问URL（用于浏览器展示）
```

#### 3.6 生成预签名下载URL

```java
import com.eimosp.fileserver.common.request.GeneratePreSignedUrlRequest;
import com.eimosp.fileserver.common.response.GeneratePresignedUrlResult;

// 构建请求
GeneratePreSignedUrlRequest request = new GeneratePreSignedUrlRequest(
    "bucket-name",                    // 桶名称
    "upload/test.jpg",                // 对象键（文件路径）
    3600                              // 过期时间（秒）
);

// 生成预签名URL
GeneratePresignedUrlResult result = fileServerClient.generatePreSignedGetUrl(request);
String preSignedUrl = result.getPreSignedUrl();  // 预签名下载URL
String fileUrl = result.getFileUrl();            // 文件访问URL
```

#### 3.7 删除文件

```java
import com.eimosp.fileserver.common.request.DeleteObjectRequest;
import com.eimosp.fileserver.common.response.DeleteObjectResult;

// 构建删除请求
DeleteObjectRequest request = new DeleteObjectRequest(
    "bucket-name",                    // 桶名称
    "upload/test.jpg"                 // 对象键（文件路径）
);

// 删除文件
DeleteObjectResult result = fileServerClient.deleteObject(request);
```

#### 3.8 创建分享链接

```java
import com.eimosp.fileserver.common.request.CreateShareRequest;
import com.eimosp.fileserver.common.response.CreateShareResult;
import com.eimosp.fileserver.common.enums.ShareMode;

// 构建分享请求
CreateShareRequest request = new CreateShareRequest(
    "bucket-name",                    // 桶名称
    "upload/test.jpg",                // 对象键（文件路径）
    ShareMode.PUBLIC,                 // 分享模式：PUBLIC/PASSWORD/TOKEN
    7 * 24 * 60 * 60                  // 有效期（秒），7天
);
// 密码模式需要设置密码
// request.setPassword("password123");

// 创建分享链接
CreateShareResult result = fileServerClient.createShare(request);
String shareUrl = result.getShareUrl();      // 分享链接URL
String shareToken = result.getShareToken();  // 分享令牌
```

#### 3.9 获取分享信息

```java
import com.eimosp.fileserver.common.request.GetShareInfoRequest;
import com.eimosp.fileserver.common.response.GetShareInfoResult;

// 构建请求
GetShareInfoRequest request = new GetShareInfoRequest("share-token");

// 获取分享信息
GetShareInfoResult result = fileServerClient.getShareInfo(request);
String fileName = result.getFileName();      // 文件名
String mode = result.getMode();             // 分享模式
Long expiresAt = result.getExpiresAt();     // 过期时间
```

### 4. 内置Web接口说明

> **注意**：以下Web接口功能需要引入 `fileserver-sdk-web-extra` 模块才会生效。如果只引入 `fileserver-sdk` 模块，这些接口不会自动注册，需要业务客户端自己实现。

SDK接入 `fileserver-sdk-web-extra` 模块后会自动注册 `RemoteFileController`，提供以下Web接口能力，无需额外开发：

#### 4.1 预签名上传URL接口

**接口路径**：`GET /file/presigned/upload`

**功能**：生成预签名上传URL，用于前端直传到存储服务上传文件，使用配置文件中默认的桶名称

**请求参数**：
- `objectKey`（必填）：对象键（文件路径），如：`test/test_image.jpg`

**响应示例**：
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "preSignedUrl": "http://minio:9000/bucket/upload/test.jpg?X-Amz-Algorithm=...",
    "fileUrl": "http://localhost:8080/file/preview/bucket/upload/test.jpg",
    "bucketName": "bucket",
    "objectKey": "upload/test.jpg",
    "expiryInSeconds": 3600
  }
}
```

**使用场景**：前端需要直接上传文件到存储服务，绕过应用服务器，减轻服务器压力。

#### 4.2 预签名下载URL接口

**接口路径**：`GET /file/presigned/download`

**功能**：从fileUrl中解析bucketName和objectKey，生成预签名下载URL，用于前端直传从存储服务下载文件

**请求参数**：
- `fileUrl`（必填）：文件访问URL，格式：`http://localhost:8080/file/preview/{bucketName}/{objectKey}`

**响应示例**：
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "preSignedUrl": "http://minio:9000/bucket/upload/test.jpg?X-Amz-Algorithm=...",
    "fileUrl": "http://localhost:8080/file/preview/bucket/upload/test.jpg",
    "bucketName": "bucket",
    "objectKey": "upload/test.jpg",
    "expiryInSeconds": 3600
  }
}
```

**使用场景**：前端需要直接下载文件，支持大文件下载，减轻服务器带宽压力。

#### 4.3 文件预览接口

**接口路径**：`GET /file/preview/{bucketName}/**`

**功能**：通过domain链接访问文件，用于浏览器直接展示文件（如图片预览），支持断点续传
**备注**：domain链接在服务端存储配置时设置

**路径说明**：
- `{bucketName}`：桶名称
- `**`：对象键（支持多级路径），如：`upload/images/photo.jpg`

**完整URL示例**：`http://localhost:8080/file/preview/bucket/upload/images/photo.jpg`

**响应**：
- 成功：返回文件流，自动设置正确的 `Content-Type` 响应头
- 失败：返回JSON格式错误信息
**备注**：前端需要对响应状态码进行判断，如果2xx表示成功，处理响应流；否则失败，处理JSON错误信息

**使用场景**：
- 图片预览：在浏览器中直接显示图片
- 文件下载：浏览器会触发下载
- 视频播放：支持HTML5视频播放器播放

**注意事项**：
- 此接口无需认证，但服务端会验证桶的拥有者账号状态
- 支持 `Range` 请求头，实现断点续传
- 自动设置 `Accept-Ranges: bytes` 响应头

### 5. 完整示例

```java
@RestController
@RequestMapping("/api/files")
public class FileController {

    @Autowired
    private FileServerClient fileServerClient;

    /**
     * 上传文件
     */
    @PostMapping("/upload")
    public Result<String> upload(@RequestParam("file") MultipartFile file) {
        try {
            PutObjectRequest request = new PutObjectRequest(
                "my-bucket",
                "upload/" + file.getOriginalFilename(),
                file.getInputStream()
            );

            ObjectMetadata metadata = new ObjectMetadata();
            metadata.setContentType(file.getContentType());
            metadata.setContentLength(file.getSize());
            metadata.setFilename(file.getOriginalFilename());
            request.setMetadata(metadata);

            PutObjectResult result = fileServerClient.putObject(request);
            return Result.success(result.getFileUrl());
        } catch (Exception e) {
            return Result.failure("上传失败: " + e.getMessage());
        }
    }

    /**
     * 下载文件
     */
    @GetMapping("/download")
    public void download(@RequestParam String objectKey,
                        HttpServletResponse response) throws Exception {
        GetObjectRequest request = new GetObjectRequest("my-bucket", objectKey);
        GetObjectResult result = fileServerClient.getObject(request);

        response.setContentType(result.getContentType());
        response.setHeader("Content-Disposition",
            "attachment; filename=\"" + result.getFilename() + "\"");

        try (InputStream is = result.getInputStream();
             OutputStream os = response.getOutputStream()) {
            IOUtils.copy(is, os);
        }
    }
}
```
