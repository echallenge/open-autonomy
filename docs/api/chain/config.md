<a id="autonomy.chain.config"></a>

# autonomy.chain.config

On-chain tools configurations.

<a id="autonomy.chain.config.ChainType"></a>

## ChainType Objects

```python
class ChainType(Enum)
```

Chain types.

<a id="autonomy.chain.config.ContractConfig"></a>

## ContractConfig Objects

```python
@dataclass
class ContractConfig()
```

Contract config class.

<a id="autonomy.chain.config.ChainConfig"></a>

## ChainConfig Objects

```python
@dataclass
class ChainConfig()
```

Chain config

<a id="autonomy.chain.config.ChainConfigs"></a>

## ChainConfigs Objects

```python
class ChainConfigs()
```

Name space for chain configs.

<a id="autonomy.chain.config.ChainConfigs.get"></a>

#### get

```python
@classmethod
def get(cls, chain_type: ChainType) -> ChainConfig
```

Return chain config for given chain type.

<a id="autonomy.chain.config.ContractConfigs"></a>

## ContractConfigs Objects

```python
class ContractConfigs()
```

A namespace for contract configs.

<a id="autonomy.chain.config.ContractConfigs.get"></a>

#### get

```python
@classmethod
def get(cls, name: str) -> ContractConfig
```

Return chain config for given chain type.

